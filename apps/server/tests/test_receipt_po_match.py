"""입고와 발주 대조 (#164, F-LEDGER-04, CHAT-03·05 `po_match`)."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from bjk_server.auth import set_tenant
from bjk_server.db.models import Movement, Notification, Part, PurchaseOrder
from bjk_server.purchasing.receipt import lead_time_days, match_receipt
from bjk_server.seed.demo import COMPANY_CODE, demo_id
from sqlalchemy import select
from sqlalchemy.orm import Session

from .conftest import auth_header

COMPANY = demo_id("company", COMPANY_CODE)
OWNER = demo_id("user", "owner")
MANAGER = demo_id("user", "manager")
P6205 = demo_id("part", "6205")
SUP_A, SUP_B = demo_id("supplier", "a"), demo_id("supplier", "b")


@pytest.fixture
def fresh(demo_db):
    demo_db.reseed()
    yield demo_db
    demo_db.reseed()


def _add_po(demo_db, **overrides) -> uuid.UUID:
    now = datetime.now(UTC)
    values = {
        "company_id": COMPANY,
        "part_id": P6205,
        "supplier_id": SUP_A,
        "qty": 10,
        "unit_price": 18000,
        "status": "ordered",
        "approved_at": now - timedelta(days=8),
        "approved_by": OWNER,
        "ordered_at": now - timedelta(days=7, hours=1),
        "ordered_by": OWNER,
    } | overrides
    with Session(demo_db.admin) as s, s.begin():
        po = PurchaseOrder(**values)
        s.add(po)
        s.flush()
        return po.id


def _receive(client, qty):
    body = {
        "client_message_id": f"in-{uuid.uuid4()}",
        "type": "IN",
        "part_id": str(P6205),
        "qty": qty,
    }
    res = client.post("/api/v1/chat/entries", json=body, headers=auth_header("worker"))
    assert res.status_code == 200, res.text
    return res.json()


def _po(demo_db, po_id) -> PurchaseOrder:
    with Session(demo_db.admin) as s:
        return s.get(PurchaseOrder, po_id)


def test_full_receipt_completes_order_with_lead_time(client, fresh):
    po_id = _add_po(fresh)
    body = _receive(client, 10)
    assert (body["po_match"], body["actual_lead_time_days"]) == ("complete", 7)
    assert body["movement"]["po_id"] == str(po_id)
    po = _po(fresh, po_id)
    assert (po.status, po.received_qty, po.implicit_order) == ("received", 10, False)
    assert po.received_at is not None


def test_partial_receipt_keeps_remaining_open(client, fresh):
    po_id = _add_po(fresh)
    body = _receive(client, 6)
    assert (body["po_match"], body["actual_lead_time_days"]) == ("partial", None)
    po = _po(fresh, po_id)
    assert (po.status, po.received_qty, po.received_at) == ("partially_received", 6, None)
    rest = _receive(client, 4)
    assert (rest["po_match"], rest["actual_lead_time_days"]) == ("complete", 7)
    assert _po(fresh, po_id).status == "received"


def test_receipt_without_mark_ordered_is_excluded_from_lead_time(client, fresh):
    po_id = _add_po(fresh, status="approved", ordered_at=None, ordered_by=None)
    body = _receive(client, 10)
    assert (body["po_match"], body["actual_lead_time_days"]) == ("complete", None)
    po = _po(fresh, po_id)
    assert (po.status, po.implicit_order, po.ordered_by) == (
        "received",
        True,
        demo_id("user", "worker"),
    )


def test_receipt_without_open_order(client, fresh):
    _add_po(
        fresh, status="cancelled", ordered_at=None, ordered_by=None, cancelled_at=datetime.now(UTC)
    )
    body = _receive(client, 3)
    assert (body["po_match"], body["actual_lead_time_days"], body["movement"]["po_id"]) == (
        "no_order",
        None,
        None,
    )


def test_over_receipt_is_mismatch_and_alerts_managers(client, fresh):
    po_id = _add_po(fresh)
    body = _receive(client, 12)
    assert body["po_match"] == "mismatch"
    assert _po(fresh, po_id).status == "received"
    with Session(fresh.admin) as s:
        users = set(s.scalars(select(Notification.user_id).where(Notification.target_id == po_id)))
        assert {OWNER, MANAGER} <= users
        assert (
            s.scalar(select(Notification.kind).where(Notification.target_id == po_id))
            == "receipt_check"
        )


def test_prefers_order_with_exact_remaining_qty(client, fresh):
    older = _add_po(fresh, qty=20)
    exact = _add_po(fresh, qty=5, approved_at=datetime.now(UTC) - timedelta(days=2))
    body = _receive(client, 5)
    assert body["movement"]["po_id"] == str(exact)
    assert _po(fresh, older).status == "ordered"


def test_supplier_or_price_mismatch_leaves_order(fresh):
    po_id = _add_po(fresh)
    with Session(fresh.app) as s, s.begin():
        set_tenant(s, COMPANY)
        part = s.get(Part, P6205)
        now = datetime.now(UTC)
        other = match_receipt(s, part, 10, OWNER, now, supplier_id=SUP_B)
        price = match_receipt(s, part, 10, OWNER, now, unit_price=15000)
        assert (other.po_match, other.po_id) == ("mismatch", None)
        assert price.po_match == "mismatch"
        assert s.get(PurchaseOrder, po_id).status == "ordered"


def test_out_movements_have_no_po_match(client, fresh):
    _add_po(fresh)
    body = {
        "client_message_id": f"out-{uuid.uuid4()}",
        "type": "OUT",
        "part_id": str(P6205),
        "qty": 1,
    }
    res = client.post("/api/v1/chat/entries", json=body, headers=auth_header("worker")).json()
    assert res["po_match"] is None
    with Session(fresh.admin) as s:
        assert s.scalar(select(Movement.po_id).where(Movement.id == res["movement"]["id"])) is None


def test_lead_time_days():
    t = datetime(2026, 11, 1, 9, tzinfo=UTC)
    assert lead_time_days(t, t + timedelta(days=6, hours=23)) == 6
    assert lead_time_days(t, t) == 0
