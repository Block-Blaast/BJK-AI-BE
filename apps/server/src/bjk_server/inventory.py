"""재고 계산. 재고는 저장하지 않고 원장 이벤트 합산으로 구한다."""

import uuid

from sqlalchemy import Subquery, func, select
from sqlalchemy.orm import Session

from bjk_server.db.models import Movement


def stock_subquery() -> Subquery:
    """part_id별 현재 재고 (part_id, stock)."""
    return (
        select(Movement.part_id, func.sum(Movement.qty).label("stock"))
        .group_by(Movement.part_id)
        .subquery("stock")
    )


def stock_of(session: Session, part_id: uuid.UUID) -> int:
    total = session.scalar(select(func.sum(Movement.qty)).where(Movement.part_id == part_id))
    return int(total or 0)
