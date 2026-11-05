"""검토 스냅샷의 열린 발주 O·C-03·최근 구매 단가 (#161, F-REVIEW-02·04)."""

from datetime import timedelta

from bjk_review import OrderRequest
from bjk_server.auth import set_tenant
from bjk_server.db.models import PurchaseOrder, Review
from bjk_server.defaults import default_settings
from bjk_server.reviews.snapshot import collect_snapshot
from sqlalchemy.orm import Session

from .test_review_run import (  # noqa: F401
    A42,
    COMPANY,
    NOW,
    SUPPLIER_A,
    _create,
    _run,
    demo_id,
    fresh,
)

OWNER = demo_id("user", "owner")


def _add(db, **overrides) -> None:
    values = {
        "company_id": COMPANY,
        "part_id": A42,
        "supplier_id": SUPPLIER_A,
        "qty": 10,
        "unit_price": 13000,
        "status": "ordered",
        "approved_at": NOW - timedelta(days=1),
        "approved_by": OWNER,
        "ordered_at": NOW - timedelta(days=1),
        "ordered_by": OWNER,
    } | overrides
    with Session(db.admin) as s, s.begin():
        s.add(PurchaseOrder(**values))


def _snapshot(db):
    with Session(db.app) as s, s.begin():
        set_tenant(s, COMPANY)
        return collect_snapshot(
            s,
            str(A42),
            OrderRequest(qty=30, supplier_id=str(SUPPLIER_A), unit_price=18000),
            now=NOW,
            settings=default_settings(),
        )


def test_open_order_fills_incoming_and_c03(fresh):  # noqa: F811
    _add(fresh)
    snapshot = _snapshot(fresh)
    assert snapshot.incoming == 10
    assert [o.qty for o in snapshot.open_orders] == [10]
    assert snapshot.open_orders[0].eta is not None
    review_id = _create(fresh)
    assert _run(fresh, review_id) == "reviewed"
    with Session(fresh.admin) as s:
        review = s.get(Review, review_id)
    codes = {c["code"] for c in review.result["checks"]}
    assert "C-03" in codes
    # F-REVIEW-10 예시 1: O 10개가 들어오면 V벨트 수정안은 0개
    assert review.result["proposal"]["qty"] == 0


def test_partial_and_closed_orders(fresh):  # noqa: F811
    _add(fresh, status="partially_received", received_qty=6)
    _add(fresh, status="received", received_qty=10, received_at=NOW)
    _add(fresh, status="cancelled", ordered_at=None, ordered_by=None, cancelled_at=NOW)
    snapshot = _snapshot(fresh)
    assert ([o.qty for o in snapshot.open_orders], snapshot.incoming) == ([4], 4)


def test_order_arriving_after_need_is_not_incoming(fresh):  # noqa: F811
    t_out = _snapshot(fresh).t_out
    assert t_out is not None
    late = (NOW - timedelta(days=1)).replace(year=NOW.year + 1)
    _add(fresh, approved_at=late, ordered_at=late)
    snapshot = _snapshot(fresh)
    assert (len(snapshot.open_orders), snapshot.incoming) == (1, 0)


def test_recent_prices_feed_price_stats(fresh):  # noqa: F811
    for price in (12000, 13000, 14000):
        _add(fresh, unit_price=price, status="received", received_qty=10, received_at=NOW)
    stats = _snapshot(fresh).price_stats
    assert (stats.n, stats.mean, stats.sigma) == (3, 13000.0, 1000.0)
    review_id = _create(fresh)
    _run(fresh, review_id)
    with Session(fresh.admin) as s:
        codes = {c["code"] for c in s.get(Review, review_id).result["checks"]}
    assert "C-05" in codes  # 18,000원 > p̄ + 2σ, p̄ × 1.05 초과


def test_no_orders_keeps_defaults(fresh):  # noqa: F811
    snapshot = _snapshot(fresh)
    assert (snapshot.incoming, snapshot.open_orders, snapshot.price_stats.n) == (0, [], 0)
