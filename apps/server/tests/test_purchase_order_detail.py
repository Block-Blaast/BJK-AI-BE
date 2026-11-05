"""발주 상세·주문 완료 표시 (#163, PO-02·03)."""

import uuid
from datetime import date, datetime, timedelta

from bjk_server.db.models import Company, Part, PurchaseOrder, Supplier
from bjk_server.seed.demo import demo_id
from sqlalchemy.orm import Session

from .conftest import auth_header
from .review_rows import add_review, vbelt_snapshot
from .test_purchase_order_api import COMPANY, NOW, OWNER, SUP_A, URL, orders  # noqa: F401


def _detail(client, order_id, user="manager"):
    return client.get(f"{URL}/{order_id}", headers=auth_header(user))


def _mark(client, order_id, body=None, user="manager"):
    return client.post(f"{URL}/{order_id}/mark-ordered", json=body or {}, headers=auth_header(user))


def _review_order(db) -> str:
    """검토(필요 시점 11/12)에서 나온 승인됨 발주."""
    with Session(db.admin) as s, s.begin():
        snapshot = vbelt_snapshot().model_copy(update={"t_out": date(2026, 11, 12)})
        review = add_review(s, snapshot=snapshot, status="approved")
        po = PurchaseOrder(
            company_id=COMPANY,
            review_id=review.id,
            part_id=demo_id("part", "a42"),
            supplier_id=SUP_A,
            qty=4,
            unit_price=18000,
            approved_at=NOW,
            approved_by=OWNER,
        )
        s.add(po)
        s.flush()
        return str(po.id)


def test_detail_has_order_message_with_need_by(client, demo_db, orders):  # noqa: F811
    order_id = _review_order(demo_db)
    res = _detail(client, order_id)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["part"]["name"] == "V벨트 A-42"
    assert (body["qty"], body["total"], body["status"]) == (4, 72000, "approved")
    assert body["approved_by"] == "김사장"
    assert body["ordered_at"] is None
    assert body["order_message"] == (
        "안녕하세요. V벨트 A-42 4개 주문 부탁드립니다. 11월 12일까지 받을 수 있을까요?"
    )


def test_order_without_review_has_message_without_date(client, orders):  # noqa: F811
    body = _detail(client, orders["received"]).json()
    assert body["order_message"] == "안녕하세요. 볼베어링 6205ZZ 10개 주문 부탁드립니다."
    assert body["actual_lead_time_days"] == 7


def test_mark_ordered_records_who_and_when(client, orders):  # noqa: F811
    at = NOW + timedelta(minutes=20)
    res = _mark(client, orders["approved"], {"ordered_at": at.isoformat()})
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "ordered"
    assert datetime.fromisoformat(res.json()["ordered_at"]) == at
    body = _detail(client, orders["approved"]).json()
    assert body["status"] == "ordered"
    assert body["ordered_by"] == "최관리"


def test_mark_ordered_defaults_to_now(client, orders):  # noqa: F811
    before = datetime.now(NOW.tzinfo)
    res = _mark(client, orders["approved_b"])
    assert res.status_code == 200
    assert datetime.fromisoformat(res.json()["ordered_at"]) >= before


def test_already_ordered_is_409(client, orders):  # noqa: F811
    res = _mark(client, orders["ordered"])
    assert res.status_code == 409
    assert res.json()["code"] == "ORDER_STATE_CONFLICT"
    assert res.json()["detail"] == {"status": "ordered", "action": "mark_ordered"}


def test_invalid_ordered_at_is_400(client, orders):  # noqa: F811
    for at in (NOW - timedelta(hours=1), datetime.now(NOW.tzinfo) + timedelta(days=1)):
        res = _mark(client, orders["approved"], {"ordered_at": at.isoformat()})
        assert res.status_code == 400
        assert res.json()["detail"] == {"field": "ordered_at"}


def test_worker_403_and_other_company_404(client, demo_db, orders):  # noqa: F811
    assert _detail(client, orders["approved"], user="worker").status_code == 403
    assert _mark(client, orders["approved"], user="worker").status_code == 403
    other = uuid.uuid4()
    with Session(demo_db.admin) as s, s.begin():
        s.add(Company(id=other, name="다른회사", code="OTHER7"))
        s.flush()
        part = Part(company_id=other, name="p", unit="개")
        supplier = Supplier(company_id=other, name="s")
        s.add_all([part, supplier])
        s.flush()
        po = PurchaseOrder(
            company_id=other,
            part_id=part.id,
            supplier_id=supplier.id,
            qty=1,
            unit_price=1,
            approved_at=NOW,
        )
        s.add(po)
        s.flush()
        other_po = po.id
    assert _detail(client, other_po).status_code == 404
    assert _mark(client, other_po).status_code == 404
