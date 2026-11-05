"""블라인드 실사 요청·응답 (F-AUDIT-06, F-CHAT-05)."""

import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from bjk_server.clock import KST
from bjk_server.db.models import AuditFlag, CompanySettings, CountRequest, Movement, Part, User
from bjk_server.defaults import DEFAULT_SETTINGS
from bjk_server.errors import ApiError, ErrorCode
from bjk_server.inventory import lock_part_stock, stock_of
from bjk_server.security import TokenClaims

# 실사조정 원장 기록의 사유. 차이 사유(AUD-04)는 실사 요청에 남긴다.
COUNT_ADJUST_REASON = "실사조정"


def count_message(part: Part) -> str:
    """담당자에게 보내는 문구. 장부 수량을 넣지 않는다(블라인드 실사)."""
    return f"{part.name} 지금 몇 개 있나요? 세어서 숫자만 보내 주세요."


def _settings(db: Session, company_id: uuid.UUID) -> tuple[int, time]:
    row = db.get(CompanySettings, company_id)
    system = row.system if row else DEFAULT_SETTINGS["system"]
    notify = row.notify if row else DEFAULT_SETTINGS["notify"]
    per_day = int(
        system.get(
            "count_per_worker_per_day", DEFAULT_SETTINGS["system"]["count_per_worker_per_day"]
        )
    )
    morning = time.fromisoformat(
        notify.get("briefing_time", DEFAULT_SETTINGS["notify"]["briefing_time"])
    )
    return per_day, morning


def _delivery_day(db: Session, assignee_id: uuid.UUID, today: date, per_day: int) -> date:
    """한도가 남은 첫 날. 보낸 날(sent_at)과 예약한 날(scheduled_for) 모두 그날 몫으로 센다."""
    start = datetime.combine(today, time.min, tzinfo=KST)
    rows = db.execute(
        select(CountRequest.sent_at, CountRequest.scheduled_for).where(
            CountRequest.assignee_id == assignee_id,
            or_(CountRequest.sent_at >= start, CountRequest.scheduled_for >= start),
        )
    ).all()
    used: dict[date, int] = {}
    for sent_at, scheduled_for in rows:
        at = sent_at or scheduled_for
        day = at.astimezone(KST).date()
        used[day] = used.get(day, 0) + 1
    day = today
    while used.get(day, 0) >= per_day:
        day += timedelta(days=1)
    return day


def request_count(
    db: Session, user: TokenClaims, flag_id: uuid.UUID, assignee_id: uuid.UUID, now: datetime
) -> CountRequest:
    """AUD-02. 열린 의심 항목의 부품을 담당자에게 세어 달라고 요청한다.

    담당자에게 오늘 이미 한도(기본 2건)만큼 보냈으면 한도가 남은 다음 날 아침으로 예약한다.
    """
    flag = db.scalar(select(AuditFlag).where(AuditFlag.id == flag_id).with_for_update())
    if flag is None:
        raise ApiError(ErrorCode.NOT_FOUND, "의심 항목을 찾을 수 없습니다.")
    if flag.status != "open":
        raise ApiError(
            ErrorCode.ALREADY_CONFIRMED,
            "이미 실사를 요청했거나 종료된 항목입니다.",
            {"status": flag.status},
        )
    assignee = db.get(User, assignee_id)
    if assignee is None or not assignee.active:
        raise ApiError(
            ErrorCode.NOT_FOUND, "담당자를 찾을 수 없습니다.", {"assignee_id": str(assignee_id)}
        )
    # 같은 담당자에게 동시에 요청이 몰려도 하루 한도를 넘지 않게 담당자 행을 잠근다.
    db.execute(select(User.id).where(User.id == assignee_id).with_for_update())

    per_day, morning = _settings(db, user.company_id)
    today = now.astimezone(KST).date()
    day = _delivery_day(db, assignee_id, today, per_day)
    part = db.get(Part, flag.part_id)
    scheduled = day != today
    request = CountRequest(
        id=uuid.uuid4(),
        company_id=user.company_id,
        audit_flag_id=flag.id,
        part_id=flag.part_id,
        assignee_id=assignee_id,
        requested_by=user.user_id,
        status="scheduled" if scheduled else "sent",
        message=count_message(part),
        scheduled_for=datetime.combine(day, morning, tzinfo=KST) if scheduled else None,
        sent_at=None if scheduled else now,
        created_at=now,
    )
    db.add(request)
    flag.status, flag.updated_at = "count_requested", now
    db.flush()
    return request


@dataclass(frozen=True)
class CountAnswer:
    request: CountRequest
    reply: str


def _diff_reply(diff: int, unit: str) -> str:
    if diff == 0:
        return "장부와 같아요. 이상 없음으로 처리했어요."
    direction = "적어요" if diff < 0 else "많아요"
    return f"장부보다 {abs(diff)}{unit} {direction}. 이유를 골라 주세요."


def delivered_requests(db: Session, assignee_id: uuid.UUID, now: datetime) -> list[CountRequest]:
    """담당자에게 전달돼 응답을 기다리는 실사 요청. 예약 건은 예약 시각부터. 오래된 요청부터."""
    return list(
        db.scalars(
            select(CountRequest)
            .where(
                CountRequest.assignee_id == assignee_id,
                or_(
                    CountRequest.status == "sent",
                    (CountRequest.status == "scheduled") & (CountRequest.scheduled_for <= now),
                ),
            )
            .order_by(CountRequest.created_at)
        )
    )


def own_delivered_request(
    db: Session, user: TokenClaims, request_id: uuid.UUID, now: datetime
) -> CountRequest:
    """담당자 본인에게 전달된 요청. 남의 요청과 아직 예약 시각 전인 요청은 없는 것으로 본다."""
    request = db.scalar(select(CountRequest).where(CountRequest.id == request_id).with_for_update())
    delivered = request is not None and (
        request.status != "scheduled" or request.scheduled_for <= now
    )
    if not delivered or request.assignee_id != user.user_id:
        raise ApiError(ErrorCode.NOT_FOUND, "실사 요청을 찾을 수 없습니다.")
    return request


def answer_count(
    db: Session, user: TokenClaims, request_id: uuid.UUID, counted_qty: int, now: datetime
) -> CountAnswer:
    """AUD-03. 센 수량으로 장부를 맞추고 그때 처음 차이를 보여준다 (F-CHAT-05).

    차이만큼 실사조정(ADJUST)을 원장에 더하고 사유를 기다린다. 차이가 0이면 원장은 그대로 두고
    의심 항목을 이상 없음으로 닫는다(같은 규칙은 억제 기간 동안 다시 뜨지 않음).
    """
    request = own_delivered_request(db, user, request_id, now)
    if request.status not in ("scheduled", "sent"):
        raise ApiError(
            ErrorCode.ALREADY_CONFIRMED, "이미 응답한 실사 요청입니다.", {"status": request.status}
        )
    part = db.get(Part, request.part_id)
    # 센 수량과 장부 차이를 구하는 사이 다른 입출고가 끼지 않게 한다 (#69).
    lock_part_stock(db, request.company_id, part.id)
    book = stock_of(db, part.id)
    diff = counted_qty - book
    if diff:
        movement = Movement(
            id=uuid.uuid4(),
            company_id=request.company_id,
            part_id=part.id,
            type="ADJUST",
            qty=diff,
            occurred_at=now,
            author_id=user.user_id,
            reason=COUNT_ADJUST_REASON,
        )
        db.add(movement)
        db.flush()
        request.adjust_movement_id = movement.id
    request.counted_qty, request.book_qty_before, request.diff = counted_qty, book, diff
    request.answered_at = now
    if request.sent_at is None:
        request.sent_at = request.scheduled_for
    flag = db.scalar(
        select(AuditFlag).where(AuditFlag.id == request.audit_flag_id).with_for_update()
    )
    if diff:
        request.status = "answered"
    else:
        request.status, request.closed_at = "closed", now
        flag.status, flag.resolution, flag.closed_at = "closed", "no_diff", now
    flag.updated_at = now
    db.flush()
    return CountAnswer(request, _diff_reply(diff, part.unit))


def close_with_reason(
    db: Session,
    user: TokenClaims,
    request_id: uuid.UUID,
    reason: str,
    note: str | None,
    now: datetime,
) -> tuple[CountRequest, AuditFlag]:
    """AUD-04. 차이 사유를 받아 실사 요청과 의심 항목을 닫는다.

    원장은 추가 전용이라 실사조정 행은 그대로 두고, 사유는 실사 요청에 남긴다.
    """
    request = own_delivered_request(db, user, request_id, now)
    if request.status != "answered":
        raise ApiError(
            ErrorCode.ALREADY_CONFIRMED,
            "차이가 확인된 응답에만 사유를 입력할 수 있습니다.",
            {"status": request.status},
        )
    request.reason, request.note = reason, note
    request.status, request.closed_at = "closed", now
    flag = db.scalar(
        select(AuditFlag).where(AuditFlag.id == request.audit_flag_id).with_for_update()
    )
    flag.status, flag.resolution, flag.closed_at, flag.updated_at = "closed", "adjusted", now, now
    db.flush()
    return request, flag
