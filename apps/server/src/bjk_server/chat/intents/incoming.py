"""재고 조회(QUERY) 답변의 입고 예정 문장 (F-CHAT-03).

열린 발주(승인됨·발주됨·부분입고)의 미입고 수량과 도착 예상일을 보여준다. 예상일은 주문 완료
시각(주문 전이면 승인 시각)에 공급사 보통 납기 LT50을 더한 날이다. LT50은 최신 공급사별 납기,
없으면 공급사 기본 납기, 그것도 없으면 7일이다(F-ANAL-04, 기능명세서 '정보가 부족할 때의 대응').
"""

import uuid
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from bjk_server.clock import KST
from bjk_server.db.models import PartSupplierMetrics, PurchaseOrder, Supplier
from bjk_server.inventory import with_merged_ids
from bjk_server.purchasing.orders import open_orders, remaining_qty

DEFAULT_LEAD_DAYS = 7


def lead_days(db: Session, part_id: uuid.UUID, supplier_id: uuid.UUID) -> int:
    lt50 = db.scalar(
        select(PartSupplierMetrics.lt50)
        .where(
            PartSupplierMetrics.part_id == part_id,
            PartSupplierMetrics.supplier_id == supplier_id,
        )
        .order_by(PartSupplierMetrics.computed_on.desc())
        .limit(1)
    )
    if lt50 is not None:
        return lt50
    supplier = db.get(Supplier, supplier_id)
    return supplier.default_lead_time_days or DEFAULT_LEAD_DAYS


def expected_date(db: Session, order: PurchaseOrder) -> date:
    start = order.ordered_at or order.approved_at
    return (
        (start + timedelta(days=lead_days(db, order.part_id, order.supplier_id)))
        .astimezone(KST)
        .date()
    )


def incoming_sentence(db: Session, part_id: uuid.UUID, unit: str) -> str:
    """예: "입고 예정 10개(11/08쯤)." 주문 전 발주가 섞여 있으면 그 건수를 덧붙인다."""
    orders = [o for o in open_orders(db, with_merged_ids(db, part_id)) if remaining_qty(o) > 0]
    if not orders:
        return "입고 예정은 없어요."
    qty = sum(remaining_qty(o) for o in orders)
    eta = min(expected_date(db, o) for o in orders)
    sentence = f"입고 예정 {qty}{unit}({eta:%m/%d}쯤)."
    waiting = sum(1 for o in orders if o.ordered_at is None)
    if waiting:
        sentence += f" 그중 {waiting}건은 아직 주문 전이에요."
    return sentence
