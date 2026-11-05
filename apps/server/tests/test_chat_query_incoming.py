from datetime import UTC, datetime

from bjk_server.db.models import Part, PurchaseOrder, Supplier
from bjk_server.seed.demo import demo_id
from sqlalchemy import update
from sqlalchemy.orm import Session

P6205 = demo_id("part", "6205")
SUPPLIER_A = demo_id("supplier", "a")
MANAGER = demo_id("user", "manager")
ORDERED = datetime(2026, 11, 2, 1, 0, tzinfo=UTC)  # 11/02 10:00 KST
APPROVED = datetime(2026, 11, 3, 1, 0, tzinfo=UTC)


def _order(s, company_id, qty, received=0, ordered_at=None, status="ordered"):
    s.add(
        PurchaseOrder(
            company_id=company_id,
            part_id=P6205,
            supplier_id=SUPPLIER_A,
            qty=qty,
            unit_price=18000,
            status=status,
            approved_at=APPROVED,
            ordered_at=ordered_at,
            ordered_by=MANAGER if ordered_at else None,
            received_qty=received,
        )
    )


def test_query_without_open_order_says_none(chat):
    reply = chat("6205 몇 개 있어?").json()["reply"]
    assert reply.startswith("볼베어링 6205ZZ 현재 재고 3개예요. 입고 예정은 없어요.")


def test_query_sums_remaining_qty_and_earliest_eta(chat, demo_db):
    with Session(demo_db.admin) as s, s.begin():
        company_id = s.get(Part, P6205).company_id
        lead = s.get(Supplier, SUPPLIER_A).default_lead_time_days
        _order(s, company_id, 10, received=4, ordered_at=ORDERED, status="partially_received")
        _order(s, company_id, 5, status="approved")
        _order(s, company_id, 7, ordered_at=ORDERED, status="cancelled")
    reply = chat("6205 몇 개 있어?").json()["reply"]
    eta = f"11/{2 + lead:02d}"
    assert f"입고 예정 11개({eta}쯤). 그중 1건은 아직 주문 전이에요." in reply


def test_eta_falls_back_to_seven_days_without_supplier_lead_time(chat, demo_db):
    with Session(demo_db.admin) as s, s.begin():
        company_id = s.get(Part, P6205).company_id
        s.execute(
            update(Supplier).where(Supplier.id == SUPPLIER_A).values(default_lead_time_days=None)
        )
        _order(s, company_id, 3, ordered_at=ORDERED)
    assert "입고 예정 3개(11/09쯤)." in chat("6205 몇 개 있어?").json()["reply"]
