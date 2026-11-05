from datetime import UTC, date, datetime, timedelta

import pytest
from bjk_server.db.models import (
    AuditFlag,
    Company,
    CountRequest,
    ExternalIndicator,
    Movement,
    Part,
    PartMetrics,
    PartSupplierMetrics,
)
from bjk_server.jobs import registry  # noqa: F401
from bjk_server.jobs.nightly import SupplierTerms, lead_time
from bjk_server.jobs.runner import run_job
from bjk_server.seed.demo import COMPANY_CODE, PARTS, demo_id
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .conftest import auth_header

NOW = datetime(2026, 11, 3, 18, 0, tzinfo=UTC)  # 2026-11-04 03:00 KST
COMPANY = demo_id("company", COMPANY_CODE)


@pytest.fixture
def nightly(demo_db):
    demo_db.reseed()

    def run():
        result = run_job(demo_db.app, "nightly", "manual", now=NOW)
        assert result.status == "ok", result.error
        return result

    return run


def _metrics(demo_db, key):
    with Session(demo_db.admin) as s:
        return s.scalar(select(PartMetrics).where(PartMetrics.part_id == demo_id("part", key)))


def test_lead_time_applies_external_weight_and_holidays():
    terms = SupplierTerms(demo_id("supplier", "a"), 18000, 10, 7, (date(2026, 11, 6),))
    today = date(2026, 11, 4)
    assert lead_time(terms, False, 1.4, 0.25, today) == 7 + 1
    # 7 × (1 + 0.25 × 1.4) = 9.45 → 10일 + 휴무 1일
    assert lead_time(terms, True, 1.4, 0.25, today) == 11
    assert lead_time(None, False, 0, 0.25, today) == 7


def test_nightly_computes_every_part(nightly, demo_db):
    summary = nightly().summary
    assert summary == {
        "companies": 1,
        "parts_computed": len(PARTS),
        "audit_flags_created": len(PARTS),
        "indicators": 2,
        "embeddings_filled": 0,
    }
    with Session(demo_db.admin) as s:
        assert s.scalar(select(func.count()).select_from(PartMetrics)) == len(PARTS)
        assert s.scalar(select(func.count()).select_from(PartSupplierMetrics)) == 8
        freight = s.scalar(
            select(ExternalIndicator)
            .where(ExternalIndicator.code == "FREIGHT")
            .order_by(ExternalIndicator.as_of.desc())
        )
        assert freight.level == "caution"


def test_bearing_6205_matches_spec_flow(nightly, demo_db):
    nightly()
    m = _metrics(demo_db, "6205")
    # 11/20 3호기 정비 4개가 재고 3개를 넘어 그날 소진
    assert m.t_out == date(2026, 11, 20)
    assert m.f_items[0]["qty"] == 4
    assert m.recommended_qty == 10  # MOQ 10
    assert m.lt90 == 10  # 기본 납기 7일 × (1 + 0.25 × r_lead), 수입 의존
    assert m.t_deadline == date(2026, 11, 10)
    assert m.loss == 50_000 * 16 * m.lt50
    assert m.external_level == "caution"
    assert m.data_mode == "statistical"


def test_rerun_same_day_replaces_with_same_values(nightly, demo_db):
    nightly()
    first = _metrics(demo_db, "m820")
    nightly()
    again = _metrics(demo_db, "m820")
    with Session(demo_db.admin) as s:
        assert s.scalar(select(func.count()).select_from(PartMetrics)) == len(PARTS)
    keys = (
        "d95",
        "d99",
        "reorder_point",
        "t_out",
        "p_out",
        "recommended_qty",
        "abc",
        "demand_class",
    )
    assert [getattr(first, k) for k in keys] == [getattr(again, k) for k in keys]


def test_short_history_uses_estimate(nightly, demo_db):
    with Session(demo_db.admin) as s, s.begin():
        part = Part(company_id=COMPANY, name="신규 부품", unit="개", monthly_estimate=30)
        s.add(part)
        s.flush()
        s.add(Movement(company_id=COMPANY, part_id=part.id, type="ADJUST", qty=5))
        part_id = part.id
    nightly()
    with Session(demo_db.admin) as s:
        m = s.scalar(select(PartMetrics).where(PartMetrics.part_id == part_id))
    assert (m.demand_class, m.data_mode) == ("insufficient", "estimated")
    assert m.d95 > 0


def test_maintenance_linked_outs_are_excluded_from_forecast(nightly, demo_db):
    nightly()
    before = _metrics(demo_db, "6204").forecast_weekly
    with Session(demo_db.admin) as s, s.begin():
        s.add(
            Movement(
                company_id=COMPANY,
                part_id=demo_id("part", "6204"),
                type="OUT",
                qty=-50,
                maintenance_id=demo_id("maintenance", "eq3:16"),
                occurred_at=NOW,
            )
        )
    nightly()
    assert _metrics(demo_db, "6204").forecast_weekly == before


def test_parts_list_shows_latest_metrics_and_filters(nightly, client):
    nightly()
    items = client.get("/api/v1/parts", headers=auth_header("worker")).json()["items"]
    bearing = next(i for i in items if i["name"] == "볼베어링 6205ZZ")
    assert bearing["t_out"] == "2026-11-20"
    assert bearing["risk_level"] == "caution"
    assert bearing["computed_at"] is not None

    caution = client.get("/api/v1/parts", params={"risk": "caution"}, headers=auth_header("worker"))
    assert {i["name"] for i in caution.json()["items"]} >= {"볼베어링 6205ZZ", "볼베어링 6204ZZ"}
    a = client.get("/api/v1/parts", params={"abc": "A"}, headers=auth_header("worker")).json()
    assert a["items"] and all(i["abc"] == "A" for i in a["items"])


def add_hidden_twin(demo_db, qty, counted_days_ago=None, suspect=False):
    """6205와 같은 카테고리·규격으로 다른 이름의 부품을 등록한다 (F-MATCH-03 숨은 재고)."""
    with Session(demo_db.admin) as s, s.begin():
        base = s.get(Part, demo_id("part", "6205"))
        twin = Part(
            company_id=COMPANY,
            name="베어링 6205 실드",
            unit="개",
            category_id=base.category_id,
            spec=dict(base.spec),
        )
        s.add(twin)
        s.flush()
        s.add(
            Movement(
                company_id=COMPANY,
                part_id=twin.id,
                type="ADJUST",
                qty=qty,
                occurred_at=NOW - timedelta(days=60),
            )
        )
        if counted_days_ago is None and not suspect:
            return twin.id
        flag = AuditFlag(
            company_id=COMPANY,
            part_id=twin.id,
            rule="COUNT_OVERDUE",
            level="low",
            status="open" if suspect else "closed",
            evidence={},
            keys=["COUNT_OVERDUE"],
        )
        s.add(flag)
        s.flush()
        if counted_days_ago is not None:
            s.add(
                CountRequest(
                    company_id=COMPANY,
                    audit_flag_id=flag.id,
                    part_id=twin.id,
                    assignee_id=demo_id("user", "worker"),
                    requested_by=demo_id("user", "manager"),
                    status="closed",
                    message="몇 개 있나요?",
                    counted_qty=qty,
                    answered_at=NOW - timedelta(days=counted_days_ago),
                )
            )
        return twin.id


@pytest.mark.parametrize(
    ("counted_days_ago", "suspect", "confirmed"),
    [(14, False, True), (45, False, False), (None, False, False), (14, True, False)],
)
def test_hidden_stock_is_confirmed_only_after_recent_count(
    nightly, demo_db, counted_days_ago, suspect, confirmed
):
    add_hidden_twin(demo_db, 800, counted_days_ago, suspect)
    nightly()
    m = _metrics(demo_db, "6205")
    assert (m.hidden_confirmed, m.hidden_unconfirmed) == ((800, 0) if confirmed else (0, 800))
    # 권장 발주량은 확인된 숨은 재고만 뺀다 (D95 11 − S 3 − H_c 800 → 0)
    assert m.recommended_qty == (0 if confirmed else 10)


def test_metrics_are_isolated_per_company(nightly, demo_db):

    from bjk_server.auth import set_tenant

    nightly()
    with Session(demo_db.app) as s:
        set_tenant(s, demo_id("company", "OTHER"))
        assert s.scalar(select(func.count()).select_from(PartMetrics)) == 0


def test_each_company_is_computed_inside_its_own_tenant(nightly, demo_db):
    other = demo_id("company", "OTHER1")
    with Session(demo_db.admin) as s, s.begin():
        s.add(Company(id=other, name="다른회사", code="OTHER1"))
        s.flush()
        part = Part(company_id=other, name="볼베어링 6205ZZ", unit="개")
        s.add(part)
        s.flush()
        s.add(Movement(company_id=other, part_id=part.id, type="ADJUST", qty=7))
    assert nightly().summary["companies"] == 2
    with Session(demo_db.admin) as s:
        rows = s.execute(
            select(PartMetrics.company_id, Part.company_id, PartMetrics.stock).join(
                Part, Part.id == PartMetrics.part_id
            )
        ).all()
    assert all(metric_company == part_company for metric_company, part_company, _ in rows)
    assert sorted(stock for company, _, stock in rows if company == other) == [7]
