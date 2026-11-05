"""발주 목록·주문 취소 (#165, PO-01·04)."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from bjk_server.auth import set_tenant
from bjk_server.db.models import PurchaseOrder
from bjk_server.purchasing.orders import open_orders
from bjk_server.seed.demo import COMPANY_CODE, demo_id
from sqlalchemy import delete
from sqlalchemy.orm import Session

from .conftest import auth_header

URL = "/api/v1/purchase-orders"
COMPANY = demo_id("company", COMPANY_CODE)
OWNER = demo_id("user", "owner")
P6205, P6204 = demo_id("part", "6205"), demo_id("part", "6204")
SUP_A, SUP_B = demo_id("supplier", "a"), demo_id("supplier", "b")
NOW = datetime(2026, 11, 4, 2, tzinfo=UTC)


@pytest.fixture
def orders(demo_db):
    """승인됨 2건(6205·6204), 발주됨 1건, 입고완료 1건(납기 7일), 주문 완료 없이 입고 1건."""
    demo_db.reseed()
    # 시드의 과거 입고 완료 발주(#12)를 지우고 이 테스트의 발주만 둔다
    with Session(demo_db.admin) as s, s.begin():
        s.execute(delete(PurchaseOrder))
    rows = {
        "approved": dict(part_id=P6205, approved_at=NOW),
        "approved_b": dict(part_id=P6204, supplier_id=SUP_B, approved_at=NOW - timedelta(hours=1)),
        "ordered": dict(
            status="ordered", ordered_at=NOW, ordered_by=OWNER, approved_at=NOW - timedelta(hours=2)
        ),
        "received": dict(
            status="received",
            ordered_at=NOW - timedelta(days=10),
            ordered_by=OWNER,
            received_qty=10,
            received_at=NOW - timedelta(days=3),
            approved_at=NOW - timedelta(days=11),
        ),
        "implicit": dict(
            status="received",
            ordered_at=NOW - timedelta(days=5),
            ordered_by=OWNER,
            implicit_order=True,
            received_qty=10,
            received_at=NOW - timedelta(days=5),
            approved_at=NOW - timedelta(days=12),
        ),
    }
    ids = {}
    with Session(demo_db.admin) as s, s.begin():
        for key, values in rows.items():
            po = PurchaseOrder(
                **(
                    {
                        "company_id": COMPANY,
                        "part_id": P6205,
                        "supplier_id": SUP_A,
                        "qty": 10,
                        "unit_price": 14800,
                        "approved_by": OWNER,
                    }
                    | values
                )
            )
            s.add(po)
            s.flush()
            ids[key] = str(po.id)
    yield ids
    demo_db.reseed()


def _list(client, user="manager", **query):
    return client.get(URL, params=query, headers=auth_header(user))


def test_list_newest_first_with_names_and_lead_time(client, orders):
    res = _list(client)
    assert res.status_code == 200, res.text
    items = res.json()["items"]
    assert [i["id"] for i in items] == [
        orders[k] for k in ("approved", "approved_b", "ordered", "received", "implicit")
    ]
    first = items[0]
    assert first["part"]["name"] == "볼베어링 6205ZZ"
    assert (first["supplier"]["name"], first["total"], first["approved_by"]) == (
        "공급사 A",
        148000,
        "김사장",
    )
    assert items[3]["actual_lead_time_days"] == 7
    assert (items[4]["actual_lead_time_days"], items[4]["ordered_by"]) == (None, None)


@pytest.mark.parametrize(
    ("query", "keys"),
    [
        ({"status": "approved"}, ["approved", "approved_b"]),
        ({"part_id": str(P6204)}, ["approved_b"]),
        ({"supplier_id": str(SUP_B)}, ["approved_b"]),
    ],
)
def test_list_filters(client, orders, query, keys):
    assert [i["id"] for i in _list(client, **query).json()["items"]] == [orders[k] for k in keys]


def test_list_cursor_pages(client, orders):
    first = _list(client, limit=2).json()
    second = _list(client, limit=2, cursor=first["next_cursor"]).json()
    third = _list(client, limit=2, cursor=second["next_cursor"]).json()
    ids = [i["id"] for page in (first, second, third) for i in page["items"]]
    assert len(set(ids)) == 5 and third["next_cursor"] is None


def test_cancel_approved_order_removes_it_from_open_orders(client, demo_db, orders):
    res = client.post(
        f"{URL}/{orders['approved']}/cancel",
        json={"reason": "재고 확인 결과 불필요"},
        headers=auth_header("manager"),
    )
    assert res.status_code == 200, res.text
    assert res.json() == {"id": orders["approved"], "status": "cancelled"}
    with Session(demo_db.app) as s, s.begin():
        set_tenant(s, COMPANY)
        po = s.get(PurchaseOrder, uuid.UUID(orders["approved"]))
        assert (po.cancel_reason, po.cancelled_at is not None) == ("재고 확인 결과 불필요", True)
        assert orders["approved"] not in {str(o.id) for o in open_orders(s, [P6205])}


@pytest.mark.parametrize("key", ["ordered", "received"])
def test_cancel_after_order_is_conflict(client, orders, key):
    res = client.post(f"{URL}/{orders[key]}/cancel", json={}, headers=auth_header("manager"))
    assert res.status_code == 409
    assert res.json()["code"] == "ORDER_STATE_CONFLICT"


def test_unknown_order_is_404(client, orders):
    res = client.post(f"{URL}/{uuid.uuid4()}/cancel", json={}, headers=auth_header("manager"))
    assert res.status_code == 404


def test_worker_forbidden(client, orders):
    assert _list(client, user="worker").status_code == 403
    res = client.post(f"{URL}/{orders['approved']}/cancel", json={}, headers=auth_header("worker"))
    assert res.status_code == 403
