"""재고 계산. 재고는 저장하지 않고 원장 이벤트 합산으로 구한다."""

import uuid

from sqlalchemy import Subquery, func, or_, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session

from bjk_server.db.models import Movement, Part, PartMetrics


def stock_subquery() -> Subquery:
    """part_id별 현재 재고 (part_id, stock).

    병합된 부품의 원장은 대표 부품에 합산한다(F-LEDGER-02).
    """
    owner = func.coalesce(Part.merged_into, Movement.part_id)
    return (
        select(owner.label("part_id"), func.sum(Movement.qty).label("stock"))
        .join(Part, Part.id == Movement.part_id)
        .group_by(owner)
        .subquery("stock")
    )


def stock_of(session: Session, part_id: uuid.UUID) -> int:
    """현재 재고. 이 부품에 병합된 부품의 원장도 더한다(F-LEDGER-02)."""
    merged = select(Part.id).where(Part.merged_into == part_id)
    total = session.scalar(
        select(func.sum(Movement.qty)).where(
            or_(Movement.part_id == part_id, Movement.part_id.in_(merged))
        )
    )
    return int(total or 0)


def lock_part_stock(session: Session, company_id: uuid.UUID, part_id: uuid.UUID) -> bool:
    """재고를 바꾸는 모든 경로가 원장 추가 전에 잡는 부품 행 잠금 (#69).

    같은 부품의 원장 추가와 잔량 조회를 커밋까지 직렬화한다. 다른 부품은 막지 않는다.
    NO KEY UPDATE는 원장 외래 키 확인에 필요한 KEY SHARE와 충돌하지 않는다.
    병합됐거나 다른 회사 부품이면 False.
    """
    locked = session.scalar(
        select(Part.id)
        .where(Part.id == part_id, Part.company_id == company_id, Part.merged_into.is_(None))
        .with_for_update(key_share=True)
    )
    return locked is not None


def latest_metrics_subquery() -> Subquery:
    """부품별 최신 근거 지표 스냅샷 한 행."""
    return (
        select(PartMetrics)
        .ext(distinct_on(PartMetrics.part_id))
        .order_by(PartMetrics.part_id, PartMetrics.computed_on.desc())
        .subquery("metrics")
    )
