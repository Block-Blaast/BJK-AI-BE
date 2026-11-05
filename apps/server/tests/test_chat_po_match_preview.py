from datetime import UTC, datetime

from bjk_server.chat.interpreter import Interpretation
from bjk_server.db.models import Part, PurchaseOrder
from bjk_server.seed.demo import demo_id
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .chat_fakes import PARSED

A42 = demo_id("part", "a42")
SUPPLIER_A = demo_id("supplier", "a")
MANAGER = demo_id("user", "manager")
APPROVED = datetime(2026, 11, 2, 1, 0, tzinfo=UTC)

PARSED.update(
    {f"V벨트 A-42 {n}개 들어옴": Interpretation("IN", "V벨트 A-42", n) for n in (4, 6, 10, 20)}
)
PARSED["V벨트 A-42 6개 씀"] = Interpretation("OUT", "V벨트 A-42", 6)


def _orders(demo_db, *rows):
    with Session(demo_db.admin) as s, s.begin():
        s.execute(delete(PurchaseOrder))
        company_id = s.get(Part, A42).company_id
        for qty, received in rows:
            s.add(
                PurchaseOrder(
                    company_id=company_id,
                    part_id=A42,
                    supplier_id=SUPPLIER_A,
                    qty=qty,
                    unit_price=18000,
                    status="partially_received" if received else "ordered",
                    approved_at=APPROVED,
                    ordered_at=APPROVED,
                    ordered_by=MANAGER,
                    received_qty=received,
                )
            )


def _preview(chat, text):
    [card] = chat(text).json()["cards"]
    return card["po_match"]


def test_in_card_previews_po_match_without_changing_orders(chat, demo_db):
    _orders(demo_db, (10, 4))
    assert _preview(chat, "V벨트 A-42 6개 들어옴") == "complete"
    assert _preview(chat, "V벨트 A-42 4개 들어옴") == "partial"
    assert _preview(chat, "V벨트 A-42 10개 들어옴") == "mismatch"
    with Session(demo_db.admin) as s:
        order = s.scalar(select(PurchaseOrder))
        assert (order.status, order.received_qty) == ("partially_received", 4)


def test_exact_remaining_order_is_picked_first(chat, demo_db):
    _orders(demo_db, (20, 0), (10, 0))
    assert _preview(chat, "V벨트 A-42 10개 들어옴") == "complete"
    assert _preview(chat, "V벨트 A-42 4개 들어옴") == "partial"


def test_no_open_order_and_out_card(chat, demo_db):
    _orders(demo_db)
    assert _preview(chat, "V벨트 A-42 4개 들어옴") == "no_order"
    assert _preview(chat, "V벨트 A-42 6개 씀") is None
