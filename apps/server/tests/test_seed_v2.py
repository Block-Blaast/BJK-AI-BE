"""시연 시드 확장 demo_v2 (#285)."""

from datetime import date, datetime, time

import pytest
from alembic import command
from bjk_server.clock import KST
from bjk_server.db.models import (
    AuditFlag,
    Movement,
    Part,
    PartMetrics,
    PurchaseOrder,
    Review,
    TwinLayout,
    User,
)
from bjk_server.seed.demo import PARTS, USERS, demo_id, seed_demo
from bjk_server.seed.demo_v2 import SAMPLE_REQUESTS, finish_demo_v2, load_data
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from .conftest import _base_url, alembic_config, ensure_app_login, temp_database

TODAY = date(2026, 11, 4)


@pytest.fixture(scope="module")
def engines():
    with temp_database(_base_url()) as url:
        command.upgrade(alembic_config(url), "head")
        admin = create_engine(url)
        app = create_engine(ensure_app_login(url))
        _seed(admin)
        yield admin, app
        admin.dispose()
        app.dispose()


def _seed(engine):
    with Session(engine) as s, s.begin():
        seed_demo(s, scenario="demo_v2", today=TODAY)


def _stock(s: Session, key: str) -> int:
    return s.scalar(select(func.sum(Movement.qty)).where(Movement.part_id == demo_id("part", key)))


def test_v2_keeps_v1_accounts_and_parts(engines):
    admin, _ = engines
    with Session(admin) as s:
        assert s.scalar(select(func.count()).select_from(User)) == len(USERS)
        for p in PARTS:
            assert _stock(s, p.key) == p.stock, p.name


def test_v2_parts_match_mock_stock(engines):
    admin, _ = engines
    data = load_data()
    with Session(admin) as s:
        assert s.scalar(select(func.count()).select_from(Part)) == len(PARTS) + len(data["parts"])
        for p in data["parts"]:
            assert (_stock(s, p.key) or 0) == p.stock, p.name


def test_running_stock_never_negative(engines):
    admin, _ = engines
    with Session(admin) as s:
        running = (
            select(
                func.sum(Movement.qty)
                .over(partition_by=Movement.part_id, order_by=(Movement.occurred_at, Movement.id))
                .label("stock")
            )
        ).subquery()
        assert s.scalar(select(func.min(running.c.stock))) >= 0


def test_received_orders_link_to_one_receipt(engines):
    admin, _ = engines
    with Session(admin) as s:
        orders = s.scalars(
            select(PurchaseOrder).where(
                PurchaseOrder.id.in_(select(Movement.po_id).where(Movement.po_id.is_not(None)))
            )
        ).all()
        assert len(orders) >= 300
        for o in orders:
            receipts = s.scalars(select(Movement).where(Movement.po_id == o.id)).all()
            assert [(m.type, m.qty) for m in receipts] == [("IN", o.qty)]
            assert o.status == "received" and o.received_at == receipts[0].occurred_at
        open_orders = s.scalars(select(PurchaseOrder).where(PurchaseOrder.status == "ordered"))
        for o in open_orders:
            assert s.scalar(select(func.count()).where(Movement.po_id == o.id)) == 0


def test_history_spans_a_year(engines):
    admin, _ = engines
    with Session(admin) as s:
        first = s.scalar(select(func.min(Movement.occurred_at)).where(Movement.type == "OUT"))
        assert (TODAY - first.astimezone(KST).date()).days >= 50 * 7
        assert s.scalar(select(func.count()).select_from(Movement)) >= 2000


def test_twin_layout_places_every_located_part(engines):
    admin, _ = engines
    with Session(admin) as s:
        layout = s.scalar(select(TwinLayout.layout))
        located = {str(i) for i in s.scalars(select(Part.id).where(Part.location.is_not(None)))}
    placed = [(p["rack_id"], p["level"], p["slot"]) for p in layout["placements"]]
    assert {p["part_id"] for p in layout["placements"]} == located
    assert len(placed) == len(set(placed))
    assert len(layout["racks"]) == 8 and len(layout["equipment"]) == 6


def test_rerun_reproduces_same_ledger(engines):
    admin, _ = engines

    def ledger():
        with Session(admin) as s:
            return s.execute(
                select(Movement.id, Movement.qty, Movement.occurred_at).order_by(Movement.id)
            ).all()

    first = ledger()
    _seed(admin)
    assert ledger() == first


def test_finish_computes_metrics_and_reviews(engines):
    admin, app = engines
    _seed(admin)
    now = datetime.combine(TODAY, time(3), tzinfo=KST)
    summary = finish_demo_v2(app, now=lambda: now)
    assert {summary[j] for j in ("nightly", "weekly-merge", "missed-scan", "briefing")} == {"ok"}
    with Session(admin) as s:
        parts = s.scalar(select(func.count()).select_from(Part))
        assert summary["parts"] == parts
        assert s.scalar(select(func.count(func.distinct(PartMetrics.part_id)))) == parts
        staff = s.scalars(select(Review).where(Review.entry == "staff_request")).all()
        assert len(staff) == len(SAMPLE_REQUESTS)
        assert {r.verdict for r in staff} >= {"ok", "revise", "hold"}
        # 정기 실사 기록이 있어 대부분의 부품은 실사 기한 지남 항목이 열리지 않는다
        overdue = s.scalar(
            select(func.count()).where(
                AuditFlag.rule == "COUNT_OVERDUE", AuditFlag.status == "open"
            )
        )
        assert overdue <= parts * 0.2
