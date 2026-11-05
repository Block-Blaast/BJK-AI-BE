"""입고와 발주 대조 (F-LEDGER-04, CHAT-03 `po_match`).

입고 한 건을 같은 부품의 열린 발주 하나와 맞춘다. 남은 수량이 입고 수량과 같은 발주를 먼저, 없으면
가장 오래된 승인부터 고른다. 상태 전이는 domain/purchase_order가 정한다.

| 결과 | 조건 | 발주 |
| --- | --- | --- |
| complete | 누적 입고가 발주 수량을 채움 | received, 실제 납기 기록 |
| partial | 누적 입고가 발주 수량보다 적음 | partially_received, 잔량 유지 |
| mismatch | 잔량보다 많이 들어옴, 또는 공급사·단가가 다름 | 관리자 알림 |
| no_order | 열린 발주 없음 | 변경 없음 |

공급사·단가가 다르면 같은 발주로 단정할 수 없어 발주는 바꾸지 않고 관리자에게만 알린다.
실제 납기는 주문 완료 시각 → 입고 완료 시각. 주문 완료 표시 없이 들어온 건은 서버가 ordered로 바꾸고
납기 표본에서 뺀다(`implicit_order`, `actual_lead_time_days: null`).
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from bjk_server.db.models import Part, PurchaseOrder, User
from bjk_server.domain.purchase_order import OPEN_STATUSES, apply_receipt
from bjk_server.notify.service import notify
from bjk_server.purchasing.orders import remaining_qty

PoMatch = Literal["complete", "partial", "mismatch", "no_order"]


@dataclass(frozen=True)
class ReceiptMatch:
    po_match: PoMatch
    # 원장 movements.po_id에 넣을 발주. 공급사·단가가 달라 대조하지 않았으면 None
    po_id: uuid.UUID | None
    # 이번 입고로 발주를 채웠고 주문 완료 시각이 있을 때만 값이 있다
    actual_lead_time_days: int | None


NO_ORDER = ReceiptMatch(po_match="no_order", po_id=None, actual_lead_time_days=None)


def _pick(orders: list[PurchaseOrder], qty: int) -> PurchaseOrder:
    exact = [o for o in orders if remaining_qty(o) == qty]
    return (exact or orders)[0]


def lead_time_days(ordered_at: datetime, received_at: datetime) -> int:
    """주문 완료 → 입고 일수. 같은 날이면 0."""
    return max(0, (received_at - ordered_at).days)


def _alert_managers(db: Session, order: PurchaseOrder, part: Part, title: str, now) -> None:
    managers = db.scalars(
        select(User.id).where(User.role.in_(("manager", "owner")), User.active.is_(True))
    ).all()
    notify(
        db,
        order.company_id,
        managers,
        "receipt_check",
        title,
        now,
        target=("order", order.id),
        dedupe_key=f"receipt_mismatch:{order.id}:{now.isoformat()}",
    )


def match_receipt(
    db: Session,
    part: Part,
    qty: int,
    user_id: uuid.UUID,
    now: datetime,
    supplier_id: uuid.UUID | None = None,
    unit_price: int | None = None,
) -> ReceiptMatch:
    """입고 qty개를 열린 발주에 반영한다.

    원장 기록과 같은 트랜잭션에서, 부품 재고 잠금을 잡은 뒤 부른다.
    """
    orders = list(
        db.scalars(
            select(PurchaseOrder)
            .where(PurchaseOrder.part_id == part.id, PurchaseOrder.status.in_(OPEN_STATUSES))
            .order_by(PurchaseOrder.approved_at, PurchaseOrder.id)
            .with_for_update()
        )
    )
    if not orders:
        return NO_ORDER
    order = _pick(orders, qty)
    if (supplier_id is not None and supplier_id != order.supplier_id) or (
        unit_price is not None and unit_price != order.unit_price
    ):
        _alert_managers(db, order, part, f"{part.name} 입고가 발주와 달라요. 확인해 주세요.", now)
        return ReceiptMatch(po_match="mismatch", po_id=None, actual_lead_time_days=None)

    over = qty > remaining_qty(order)
    outcome = apply_receipt(order.status, order.qty, order.received_qty, qty)  # type: ignore[arg-type]
    if outcome.implicit_order:
        # 주문 완료 표시 없이 입고: 발주됨으로 바꾸되 납기 표본에서 뺀다 (F-LEDGER-04)
        order.ordered_at, order.ordered_by, order.implicit_order = now, user_id, True
    order.status, order.received_qty = outcome.status, outcome.received_qty
    days = None
    if outcome.completed:
        order.received_at = now
        if not order.implicit_order and order.ordered_at is not None:
            days = lead_time_days(order.ordered_at, now)
    if over:
        _alert_managers(
            db, order, part, f"{part.name} 입고가 발주 수량보다 많아요. 확인해 주세요.", now
        )
        return ReceiptMatch(po_match="mismatch", po_id=order.id, actual_lead_time_days=days)
    return ReceiptMatch(
        po_match="complete" if outcome.completed else "partial",
        po_id=order.id,
        actual_lead_time_days=days,
    )
