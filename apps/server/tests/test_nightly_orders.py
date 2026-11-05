"""nightly의 실제 납기 LT50·LT90와 입고 예정 O 반영 (F-ANAL-04·09, F-LEDGER-04)."""

from datetime import timedelta

from bjk_server.db.models import Part, PartMetrics, PartSupplierMetrics, PurchaseOrder
from bjk_server.domain.purchase_order import lead_quantiles
from sqlalchemy import select
from sqlalchemy.orm import Session

from .test_nightly import COMPANY, NOW, demo_id, nightly  # noqa: F401

BOLT = demo_id("part", "m820")
OWNER = demo_id("user", "owner")


def _add(db, supplier_id, **overrides):
    values = {
        "company_id": COMPANY,
        "part_id": BOLT,
        "supplier_id": supplier_id,
        "qty": 100,
        "unit_price": 50,
        "status": "received",
        "approved_at": NOW - timedelta(days=40),
        "approved_by": OWNER,
        "ordered_by": OWNER,
        "received_qty": 100,
    } | overrides
    with Session(db.admin) as s, s.begin():
        s.add(PurchaseOrder(**values))


def _supplier(db):
    with Session(db.admin) as s:
        return s.get(Part, BOLT).default_supplier_id


def _rows(db):
    with Session(db.admin) as s:
        metrics = s.scalar(select(PartMetrics).where(PartMetrics.part_id == BOLT))
        supplier = s.scalar(
            select(PartSupplierMetrics).where(
                PartSupplierMetrics.part_id == BOLT,
                PartSupplierMetrics.supplier_id == metrics.default_supplier_id,
            )
        )
        return metrics, supplier


def test_actual_lead_times_set_lt50_lt90(demo_db, nightly):  # noqa: F811
    nightly()
    before, _ = _rows(demo_db)
    supplier = _supplier(demo_db)
    for days in (5, 6, 7, 8):
        ordered = NOW - timedelta(days=30)
        _add(demo_db, supplier, ordered_at=ordered, received_at=ordered + timedelta(days=days))
    # 주문 완료 표시 없이 입고된 건은 표본에서 뺀다
    _add(
        demo_db,
        supplier,
        implicit_order=True,
        ordered_at=NOW - timedelta(days=60),
        received_at=NOW - timedelta(days=1),
    )
    nightly()
    metrics, row = _rows(demo_db)
    q50, q90 = lead_quantiles([5, 6, 7, 8], False, 0, 0.25)
    assert row.samples == 4
    assert (row.lt50 >= q50, row.lt90 >= q90, row.lt50 <= row.lt90) == (True, True, True)
    assert (metrics.lt50, metrics.lt90) == (row.lt50, row.lt90)
    assert metrics.period_days == row.lt90 + (before.period_days - before.lt90)


def test_open_orders_reduce_recommended_qty(demo_db, nightly):  # noqa: F811
    nightly()
    before, _ = _rows(demo_db)
    assert before.recommended_qty > 0
    _add(
        demo_db,
        _supplier(demo_db),
        status="ordered",
        received_qty=0,
        qty=before.d95 + 50,
        ordered_at=NOW - timedelta(days=1),
    )
    nightly()
    after, _ = _rows(demo_db)
    assert after.recommended_qty == 0
    assert after.d95 == before.d95
