"""재고 계산. 재고는 저장하지 않고 원장 이벤트 합산으로 구한다."""

import uuid

from sqlalchemy import Subquery, func, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session

from bjk_server.db.models import Movement, PartMetrics


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


def latest_metrics_subquery() -> Subquery:
    """부품별 최신 근거 지표 스냅샷 한 행."""
    return (
        select(PartMetrics)
        .ext(distinct_on(PartMetrics.part_id))
        .order_by(PartMetrics.part_id, PartMetrics.computed_on.desc())
        .subquery("metrics")
    )
