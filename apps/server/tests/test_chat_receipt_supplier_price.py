"""채팅 입고의 공급사·단가 발주 대조 (F-LEDGER-04, CHAT-01·03·05)."""

import uuid

from bjk_server.chat.interpreter import Interpretation
from bjk_server.db.models import Notification, PurchaseOrder
from sqlalchemy import select
from sqlalchemy.orm import Session

from .chat_fakes import PARSED
from .conftest import auth_header
from .test_chat_po_match_preview import A42, _orders

SUPPLIER_B = "공급사 B"

PARSED.update(
    {
        "V벨트 A-42 10개 공급사 B에서 들어옴": Interpretation(
            "IN", "V벨트 A-42", 10, supplier_text=SUPPLIER_B
        ),
        "V벨트 A-42 10개 15000원에 들어옴": Interpretation(
            "IN", "V벨트 A-42", 10, unit_price=15000
        ),
        "V벨트 A-42 10개 18000원에 들어옴": Interpretation(
            "IN", "V벨트 A-42", 10, unit_price=18000
        ),
    }
)


def _confirm(client, entry_id):
    res = client.post(
        f"/api/v1/chat/entries/{entry_id}/confirm", json={}, headers=auth_header("worker")
    )
    assert res.status_code == 200, res.text
    return res.json()


def _status(demo_db):
    with Session(demo_db.admin) as s:
        return s.scalar(select(PurchaseOrder.status).where(PurchaseOrder.part_id == A42))


def test_other_supplier_is_mismatch_in_card_and_confirm(client, chat, demo_db):
    _orders(demo_db, (10, 0))
    [card] = chat("V벨트 A-42 10개 공급사 B에서 들어옴").json()["cards"]
    assert card["po_match"] == "mismatch"
    body = _confirm(client, card["entry_id"])
    assert (body["po_match"], body["movement"]["po_id"]) == ("mismatch", None)
    assert _status(demo_db) == "ordered"
    with Session(demo_db.admin) as s:
        kinds = s.scalars(select(Notification.kind)).all()
    assert "receipt_check" in kinds


def test_other_unit_price_is_mismatch(client, chat, demo_db):
    _orders(demo_db, (10, 0))
    [card] = chat("V벨트 A-42 10개 15000원에 들어옴").json()["cards"]
    assert card["po_match"] == "mismatch"
    assert _confirm(client, card["entry_id"])["po_match"] == "mismatch"
    assert _status(demo_db) == "ordered"


def test_same_unit_price_completes(client, chat, demo_db):
    _orders(demo_db, (10, 0))
    [card] = chat("V벨트 A-42 10개 18000원에 들어옴").json()["cards"]
    assert card["po_match"] == "complete"
    assert _confirm(client, card["entry_id"])["po_match"] == "complete"
    assert _status(demo_db) == "received"


def test_form_entry_passes_supplier_and_price(client, chat, demo_db):
    _orders(demo_db, (10, 0))
    body = {
        "client_message_id": f"f-{uuid.uuid4()}",
        "type": "IN",
        "part_id": str(A42),
        "qty": 10,
        "unit_price": 15000,
    }
    res = client.post("/api/v1/chat/entries", json=body, headers=auth_header("worker"))
    assert res.json()["po_match"] == "mismatch"
