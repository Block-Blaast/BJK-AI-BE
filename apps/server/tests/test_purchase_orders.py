"""발주 테이블과 열린 발주·최근 단가 조회 (#161, F-REVIEW-02, F-APPROVAL-02)."""

from datetime import UTC, datetime, timedelta

import pytest
from bjk_server.auth import set_tenant
from bjk_server.db.models import PurchaseOrder
from bjk_server.purchasing.orders import open_orders, open_qty, recent_price_stats
from bjk_server.seed.demo import COMPANY_CODE, demo_id
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

COMPANY = demo_id("company", COMPANY_CODE)
OWNER = demo_id("user", "owner")
P6205 = demo_id("part", "6205")
P6204 = demo_id("part", "6204")
SUP_A = demo_id("supplier", "a")
NOW = datetime(2026, 11, 4, 3, tzinfo=UTC)


@pytest.fixture
def fresh(demo_db):
    demo_db.reseed()
    # 시드의 과거 입고 완료 발주(#12)를 지우고 이 테스트의 발주만 둔다
    with Session(demo_db.admin) as s, s.begin():
        s.execute(delete(PurchaseOrder))
    yield demo_db
    demo_db.reseed()


def _po(**overrides) -> PurchaseOrder:
    values = {
        "company_id": COMPANY,
        "part_id": P6205,
        "supplier_id": SUP_A,
        "qty": 10,
        "unit_price": 18000,
        "approved_at": NOW,
        "approved_by": OWNER,
    } | overrides
    return PurchaseOrder(**values)


def _app_session(demo_db, company=COMPANY) -> Session:
    session = Session(demo_db.app)
    session.begin()
    set_tenant(session, company)
    return session


def test_open_orders_and_remaining_qty(fresh):
    with _app_session(fresh) as s:
        s.add_all(
            [
                _po(),
                _po(
                    status="ordered",
                    ordered_at=NOW,
                    ordered_by=OWNER,
                    approved_at=NOW + timedelta(1),
                ),
                _po(
                    status="partially_received",
                    qty=10,
                    received_qty=4,
                    approved_at=NOW + timedelta(hours=1),
                ),
                _po(status="received", received_qty=10, received_at=NOW),
                _po(status="cancelled", cancelled_at=NOW),
                _po(part_id=P6204, qty=3),
            ]
        )
        s.flush()
        orders = open_orders(s, [P6205])
        assert [o.status for o in orders] == ["approved", "partially_received", "ordered"]
        assert open_qty(s, [P6205, P6204]) == {P6205: 10 + 10 + 6, P6204: 3}
        assert open_qty(s, []) == {} and open_orders(s, []) == []
        s.rollback()


def test_recent_price_stats_skips_cancelled_and_old(fresh):
    with _app_session(fresh) as s:
        s.add_all(
            [
                _po(unit_price=12000, status="received", received_qty=10, received_at=NOW),
                _po(unit_price=14000),
                _po(unit_price=99000, status="cancelled", cancelled_at=NOW),
                _po(unit_price=1000, approved_at=NOW - timedelta(days=400)),
            ]
        )
        s.flush()
        stats = recent_price_stats(s, [P6205], NOW)
        assert (stats.n, stats.mean, round(stats.std, 1)) == (2, 13000.0, 1414.2)
        assert recent_price_stats(s, [P6204], NOW).n == 0
        s.rollback()


@pytest.mark.parametrize(
    "overrides",
    [
        {"status": "shipped"},
        {"qty": 0},
        {"unit_price": -1},
        {"ordered_at": NOW},  # 주문 완료자 없이 시각만
    ],
)
def test_constraints_reject_invalid_rows(fresh, overrides):
    with _app_session(fresh) as s:
        s.add(_po(**overrides))
        with pytest.raises(IntegrityError):
            s.flush()
        s.rollback()


def test_other_company_cannot_see_orders(fresh):
    with _app_session(fresh) as s:
        s.add(_po())
        s.commit()
    with _app_session(fresh, demo_id("company", "OTHER")) as s:
        assert s.scalars(select(PurchaseOrder)).all() == []
        s.rollback()
