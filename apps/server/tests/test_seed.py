import statistics
from datetime import date

import pytest
from alembic import command
from bjk_server.db.models import Category, Company, Movement, Part, PurchaseOrder, User
from bjk_server.security import verify_secret
from bjk_server.seed.demo import (
    DEFAULT_SUPPLIER,
    ORDER_PRICES,
    PARTS,
    SUPPLIER_PARTS,
    SUPPLIERS,
    USERS,
    demo_id,
    seed_demo,
)
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from .conftest import _base_url, alembic_config, temp_database

TODAY = date(2026, 11, 4)


@pytest.fixture(scope="module")
def seed_engine():
    with temp_database(_base_url()) as url:
        command.upgrade(alembic_config(url), "head")
        engine = create_engine(url)
        yield engine
        engine.dispose()


def _seed(engine, today=TODAY):
    with Session(engine) as s, s.begin():
        seed_demo(s, today=today)


def _snapshot(engine):
    with Session(engine) as s:
        return {
            "movements": s.execute(
                select(
                    Movement.id, Movement.part_id, Movement.type, Movement.qty, Movement.occurred_at
                ).order_by(Movement.id)
            ).all(),
            "parts": s.scalars(select(Part.id).order_by(Part.id)).all(),
            "orders": s.execute(
                select(
                    PurchaseOrder.id,
                    PurchaseOrder.qty,
                    PurchaseOrder.ordered_at,
                    PurchaseOrder.received_at,
                ).order_by(PurchaseOrder.id)
            ).all(),
        }


def test_seed_creates_demo_company(seed_engine):
    _seed(seed_engine)
    with Session(seed_engine) as s:
        company = s.scalar(select(Company))
        assert (company.name, company.code) == ("한서정밀", "HS7F3K")
        assert s.scalar(select(func.count()).select_from(User)) == len(USERS)
        names = set(s.scalars(select(Category.name)))
        assert {"베어링", "V벨트·전동벨트", "볼트·너트", "절삭유·윤활유"} <= names


def test_event_sum_matches_target_stock(seed_engine):
    _seed(seed_engine)
    with Session(seed_engine) as s:
        for p in PARTS:
            stock = s.scalar(
                select(func.sum(Movement.qty)).where(Movement.part_id == demo_id("part", p.key))
            )
            assert stock == p.stock, p.name


def test_history_covers_at_least_8_weeks(seed_engine):
    _seed(seed_engine)
    with Session(seed_engine) as s:
        first = s.scalar(select(func.min(Movement.occurred_at)).where(Movement.type == "OUT"))
        assert (TODAY - first.date()).days >= 8 * 7


def test_demo_accounts_can_be_verified(seed_engine):
    _seed(seed_engine)
    with Session(seed_engine) as s:
        for u in USERS:
            user = s.get(User, demo_id("user", u.key))
            if u.password:
                assert verify_secret(user.password_hash, u.password)
            if u.pin:
                assert verify_secret(user.pin_hash, u.pin)


def test_rerun_reproduces_same_state(seed_engine):
    _seed(seed_engine)
    first = _snapshot(seed_engine)
    _seed(seed_engine)
    assert _snapshot(seed_engine) == first


def test_unknown_scenario_is_rejected(seed_engine):
    with Session(seed_engine) as s, pytest.raises(ValueError):
        seed_demo(s, scenario="nope")


def test_received_orders_give_lead_time_samples(seed_engine):
    """공급사·부품마다 입고 완료 발주가 있고, 납기는 기본 납기 -1 ~ +3일 (#12)."""
    _seed(seed_engine)
    lead_days = {demo_id("supplier", key): days for key, _, _, days in SUPPLIERS}
    with Session(seed_engine) as s:
        orders = s.scalars(select(PurchaseOrder)).all()
        history_start = s.scalar(select(func.min(Movement.occurred_at)))
    pairs = {
        (demo_id("part", p), demo_id("supplier", sup))
        for p, sup, *_ in SUPPLIER_PARTS
        # 단가 예시를 맞춘 부품은 기본 공급사 이력만 둔다
        if p not in ORDER_PRICES or DEFAULT_SUPPLIER[p] == sup
    }
    assert {(o.part_id, o.supplier_id) for o in orders} == pairs
    for o in orders:
        assert o.status == "received" and o.received_qty == o.qty
        assert not o.implicit_order and o.review_id is None
        lead = (o.received_at - o.ordered_at).days
        assert lead_days[o.supplier_id] - 1 <= lead <= lead_days[o.supplier_id] + 3
        # 초기 재고 이관 전 기록이라 원장 입고와 연결하지 않는다
        assert o.received_at < history_start
    assert len(orders) >= 2 * len(pairs)


def test_vbelt_order_prices_match_spec_example(seed_engine):
    """API 명세서 REV-02 예시: 최근 구매 단가 평균 13,000원, 표준편차 약 1,200원, 4건."""

    _seed(seed_engine)
    with Session(seed_engine) as s:
        prices = s.scalars(
            select(PurchaseOrder.unit_price).where(PurchaseOrder.part_id == demo_id("part", "a42"))
        ).all()
    assert len(prices) == 4
    assert statistics.mean(prices) == 13000
    assert round(statistics.stdev(prices)) == 1200
