"""실시간 이벤트 발행과 조회 (API 명세서 NOT-03).

이벤트는 업무 기록과 같은 트랜잭션에 저장해, 기록이 롤백되면 이벤트도 남지 않는다.
SSE 연결은 저장된 이벤트를 짧은 간격으로 조회해 보낸다.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from bjk_server.db.models import ServerEvent

EventType = Literal[
    "stock.changed", "review.created", "review.progress", "review.decided", "audit.flagged"
]

# 먼저 시작해 늦게 커밋된 트랜잭션의 이벤트는 id가 이미 보낸 것보다 작을 수 있다.
# 이 시간 안의 이벤트는 id와 관계없이 다시 보고, 보낸 id는 건너뛴다.
LATE_COMMIT_WINDOW_SECONDS = 30


def publish(
    session: Session, company_id: uuid.UUID, type_: EventType, data: dict[str, Any]
) -> None:
    session.add(ServerEvent(company_id=company_id, type=type_, data=data))


@dataclass(frozen=True)
class EventRow:
    id: int
    type: str
    data: dict[str, Any]
    created_at: datetime


def latest_id(session: Session) -> int:
    """현재 회사(RLS)의 마지막 이벤트 id. 이벤트가 없으면 0."""
    return int(session.scalar(select(func.coalesce(func.max(ServerEvent.id), 0))))


def read_after(session: Session, last_id: int, limit: int = 500) -> list[EventRow]:
    """last_id 이후 이벤트와, 늦게 커밋됐을 수 있는 최근 이벤트를 id 순으로 준다."""
    recent = func.now() - func.make_interval(0, 0, 0, 0, 0, 0, LATE_COMMIT_WINDOW_SECONDS)
    rows = session.execute(
        select(ServerEvent.id, ServerEvent.type, ServerEvent.data, ServerEvent.created_at)
        .where(or_(ServerEvent.id > last_id, ServerEvent.created_at > recent))
        .order_by(ServerEvent.id)
        .limit(limit)
    )
    return [EventRow(r.id, r.type, r.data, r.created_at) for r in rows]
