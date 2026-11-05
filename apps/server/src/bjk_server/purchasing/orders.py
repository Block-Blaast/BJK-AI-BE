"""발주 조회 (F-REVIEW-02 O·p̄·σ_p·n, C-03, F-LEDGER-03 초안 차단).

열린 발주는 승인됨·발주됨·부분입고다. 주문하지 않은 승인됨도 넣어 같은 부품을 두 번 발주하지
않게 한다(F-APPROVAL-02). 테넌트가 설정된 세션에서 부른다.
"""

import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bjk_server.db.models import PurchaseOrder
from bjk_server.domain.purchase_order import OPEN_STATUSES, PriceStats, price_stats

# 최근 구매 단가로 보는 기간과 최대 건수
PRICE_LOOKBACK = timedelta(days=365)
PRICE_MAX_SAMPLES = 20


def open_orders(db: Session, part_ids: Sequence[uuid.UUID]) -> list[PurchaseOrder]:
    """부품들의 열린 발주. 오래된 승인부터."""
    if not part_ids:
        return []
    return list(
        db.scalars(
            select(PurchaseOrder)
            .where(
                PurchaseOrder.part_id.in_(part_ids),
                PurchaseOrder.status.in_(OPEN_STATUSES),
            )
            .order_by(PurchaseOrder.approved_at, PurchaseOrder.id)
        )
    )


def remaining_qty(order: PurchaseOrder) -> int:
    """아직 들어오지 않은 수량."""
    return max(0, order.qty - order.received_qty)


def open_qty(db: Session, part_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, int]:
    """부품별 열린 발주의 미입고 수량 합. 열린 발주가 없는 부품은 빠진다."""
    if not part_ids:
        return {}
    rows = db.execute(
        select(
            PurchaseOrder.part_id,
            func.sum(func.greatest(PurchaseOrder.qty - PurchaseOrder.received_qty, 0)),
        )
        .where(PurchaseOrder.part_id.in_(part_ids), PurchaseOrder.status.in_(OPEN_STATUSES))
        .group_by(PurchaseOrder.part_id)
    )
    return {part_id: int(qty) for part_id, qty in rows}


def recent_price_stats(db: Session, part_ids: Sequence[uuid.UUID], now: datetime) -> PriceStats:
    """최근 1년 취소되지 않은 발주 단가(최신 20건)의 통계.

    병합·같은 규격 부품은 part_ids로 함께 넘긴다.
    """
    if not part_ids:
        return price_stats([])
    prices = db.scalars(
        select(PurchaseOrder.unit_price)
        .where(
            PurchaseOrder.part_id.in_(part_ids),
            PurchaseOrder.status != "cancelled",
            PurchaseOrder.approved_at >= now - PRICE_LOOKBACK,
        )
        .order_by(PurchaseOrder.approved_at.desc())
        .limit(PRICE_MAX_SAMPLES)
    ).all()
    return price_stats(list(prices))
