"""알림 만들기 (기능명세서 F-NOTI-01·03·04).

- 모든 알림은 `notifications`에 한 줄씩 남긴다. 받는 사람마다 한 줄이다.
- 같은 사건은 `dedupe_key`로 사용자마다 한 번만 만든다. 마감 2일 전 재알림처럼 다시 보낼 때는
  부르는 쪽이 다른 키(예: `review_urgent:<id>:d-2`)를 쓴다.
- 조용한 시간(회사 설정 `notify.quiet_hours`, Asia/Seoul)에 생긴 알림은 끝나는 시각으로 미룬다.
  긴급 건도 같다. 미룬 알림은 그 시각 전에는 목록에 보이지 않는다.
"""

import uuid
from collections.abc import Iterable
from datetime import datetime, time, timedelta
from typing import Literal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from bjk_server.clock import KST
from bjk_server.db.models import CompanySettings, Notification
from bjk_server.defaults import DEFAULT_SETTINGS

Kind = Literal[
    "review_completed",
    "review_urgent",
    "briefing",
    "decision_result",
    "order_check",
    "receipt_check",
    "count_request",
    "maintenance_check",
]
Channel = Literal["push", "in_app", "chat"]
TargetType = Literal["part", "review", "order", "count", "maintenance"]


def _hhmm(value: str) -> time:
    hour, minute = value.split(":")
    return time(int(hour), int(minute))


def release_at(now: datetime, quiet_hours: dict[str, str]) -> datetime:
    """조용한 시간이면 끝나는 시각, 아니면 지금. 시작 > 끝이면 자정을 넘는 구간이다."""
    start, end = _hhmm(quiet_hours["start"]), _hhmm(quiet_hours["end"])
    if start == end:
        return now
    local = now.astimezone(KST)
    clock_time = local.time()
    if start < end:
        quiet = start <= clock_time < end
        end_day = local.date()
    else:
        quiet = clock_time >= start or clock_time < end
        end_day = local.date() + timedelta(days=1) if clock_time >= start else local.date()
    if not quiet:
        return now
    return datetime.combine(end_day, end, tzinfo=KST)


def quiet_hours_of(db: Session, company_id: uuid.UUID) -> dict[str, str]:
    notify = db.scalar(
        select(CompanySettings.notify).where(CompanySettings.company_id == company_id)
    )
    return (notify or {}).get("quiet_hours", DEFAULT_SETTINGS["notify"]["quiet_hours"])


def notify(
    db: Session,
    company_id: uuid.UUID,
    user_ids: Iterable[uuid.UUID],
    kind: Kind,
    title: str,
    now: datetime,
    *,
    channels: Iterable[Channel] = ("push", "in_app"),
    target: tuple[TargetType, uuid.UUID] | None = None,
    dedupe_key: str | None = None,
) -> list[uuid.UUID]:
    """받는 사람마다 알림을 만든다. 이미 같은 키로 받은 사람은 건너뛰고, 새로 만든 ID를 돌려준다."""
    sent_at = release_at(now, quiet_hours_of(db, company_id))
    target_type, target_id = target if target else (None, None)
    created: list[uuid.UUID] = []
    for user_id in user_ids:
        stmt = (
            insert(Notification)
            .values(
                company_id=company_id,
                user_id=user_id,
                kind=kind,
                target_type=target_type,
                target_id=target_id,
                title=title,
                channels=list(channels),
                dedupe_key=dedupe_key,
                sent_at=sent_at,
            )
            .on_conflict_do_nothing(constraint="uq_notifications_user_dedupe")
            .returning(Notification.id)
        )
        new_id = db.scalar(stmt)
        if new_id is not None:
            created.append(new_id)
    return created
