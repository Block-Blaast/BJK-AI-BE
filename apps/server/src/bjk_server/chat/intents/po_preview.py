"""입고(IN) 확인 카드의 발주 대조 미리 보기 (CHAT-01 `po_match`, F-LEDGER-04).

확정(CHAT-03) 때의 대조(`purchasing.receipt.match_receipt`)와 같은 규칙으로 고르되, 발주를 바꾸거나
알림을 보내지 않는다. 카드에는 공급사·단가가 없어 수량만 비교한다. 확정 시점에 다른 입고가 먼저
반영되면 실제 결과는 응답의 `po_match`가 정본이다.
"""

import uuid

from sqlalchemy.orm import Session

from bjk_server.purchasing.orders import open_orders, remaining_qty
from bjk_server.purchasing.receipt import PoMatch


def preview_po_match(db: Session, part_id: uuid.UUID, qty: int | None) -> PoMatch | None:
    """수량이 없으면 None(확정할 때 입력받으므로 미리 볼 수 없음)."""
    if not qty:
        return None
    orders = open_orders(db, [part_id])
    if not orders:
        return "no_order"
    exact = [o for o in orders if remaining_qty(o) == qty]
    order = (exact or orders)[0]
    if qty > remaining_qty(order):
        return "mismatch"
    return "complete" if order.received_qty + qty >= order.qty else "partial"
