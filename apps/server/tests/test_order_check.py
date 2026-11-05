from datetime import UTC, datetime, timedelta

import pytest
from bjk_server.db.models import Notification, Part, PartMetrics, PurchaseOrder, Supplier
from bjk_server.jobs import registry  # noqa: F401
from bjk_server.jobs.runner import run_job
from bjk_server.seed.demo import demo_id
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

NOW = datetime(2026, 11, 4, 22, 0, tzinfo=UTC)  # 11/05 07:00 KST
A42 = demo_id("part", "a42")
SUPPLIER_A = demo_id("supplier", "a")
MANAGER = demo_id("user", "manager")
OWNER = demo_id("user", "owner")


@pytest.fixture
def db(demo_db):
    demo_db.reseed()
    with Session(demo_db.admin) as s, s.begin():
        s.execute(delete(PurchaseOrder))
        s.execute(delete(PartMetrics))
        s.execute(
            update(Supplier).where(Supplier.id == SUPPLIER_A).values(default_lead_time_days=7)
        )
    return demo_db


def _order(db, *, approved_at, ordered_at=None, status="approved", approved_by=OWNER, received=0):
    with Session(db.admin) as s, s.begin():
        po = PurchaseOrder(
            company_id=s.get(Part, A42).company_id,
            part_id=A42,
            supplier_id=SUPPLIER_A,
            qty=30,
            unit_price=18000,
            status=status,
            approved_at=approved_at,
            approved_by=approved_by,
            ordered_at=ordered_at,
            ordered_by=MANAGER if ordered_at else None,
            received_qty=received,
        )
        s.add(po)
        s.flush()
        return po.id


def _run(db, now=NOW):
    result = run_job(db.app, "order-check", "manual", now=now)
    assert result.status == "ok", result.error
    return result.summary


def _notes(db, kind):
    with Session(db.admin) as s:
        rows = s.scalars(select(Notification).where(Notification.kind == kind)).all()
        return sorted((n.user_id, n.target_id, n.title) for n in rows)


def test_unordered_after_24h_asks_approver_once(db):
    late = _order(db, approved_at=NOW - timedelta(hours=25))
    _order(db, approved_at=NOW - timedelta(hours=23))
    assert _run(db) == {"order_check": 1, "receipt_check": 0}
    assert _notes(db, "order_check") == [(OWNER, late, "V벨트 A-42 30개 발주를 주문하셨나요?")]
    assert _run(db, NOW + timedelta(days=1))["order_check"] == 1  # 23시간 건만 새로
    assert len(_notes(db, "order_check")) == 2


def test_unordered_without_approver_goes_to_managers(db):
    _order(db, approved_at=NOW - timedelta(days=2), approved_by=None)
    _run(db)
    assert {user for user, _, _ in _notes(db, "order_check")} == {MANAGER, OWNER}


def test_overdue_receipt_uses_lt90_then_supplier_lead(db):
    overdue = _order(
        db,
        approved_at=NOW - timedelta(days=9),
        ordered_at=NOW - timedelta(days=8),
        status="partially_received",
        received=10,
    )
    _order(
        db,
        approved_at=NOW - timedelta(days=6),
        ordered_at=NOW - timedelta(days=6),
        status="ordered",
    )
    _order(
        db,
        approved_at=NOW - timedelta(days=30),
        ordered_at=NOW - timedelta(days=29),
        status="received",
        received=30,
    )
    assert _run(db) == {"order_check": 0, "receipt_check": 2}
    assert {t for _, t, _ in _notes(db, "receipt_check")} == {overdue}
    assert _run(db)["receipt_check"] == 0


def test_lt90_from_part_metrics_wins(db, demo_db):
    _order(
        db,
        approved_at=NOW - timedelta(days=9),
        ordered_at=NOW - timedelta(days=8),
        status="ordered",
    )
    assert run_job(demo_db.app, "nightly", "manual", now=NOW - timedelta(hours=4)).status == "ok"
    with Session(db.admin) as s:
        lt90 = s.scalar(
            select(PartMetrics.lt90)
            .where(PartMetrics.part_id == A42)
            .order_by(PartMetrics.computed_on.desc())
            .limit(1)
        )
    expected = 2 if lt90 < 8 else 0
    assert _run(db)["receipt_check"] == expected
