"""블라인드 실사 요청·응답 (F-AUDIT-06, F-CHAT-05)."""

import uuid
from datetime import date, datetime, time, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from bjk_server.clock import KST
from bjk_server.db.models import AuditFlag, CompanySettings, CountRequest, Part, User
from bjk_server.defaults import DEFAULT_SETTINGS
from bjk_server.errors import ApiError, ErrorCode
from bjk_server.security import TokenClaims


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
