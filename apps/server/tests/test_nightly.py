from datetime import UTC, date, datetime

import pytest
from bjk_server.db.models import ExternalIndicator, Movement, Part, PartMetrics, PartSupplierMetrics
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
        result = run_job(demo_db.admin, "nightly", "manual", now=NOW)
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
    assert summary == {"companies": 1, "parts_computed": len(PARTS), "indicators": 2}
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


def test_metrics_are_isolated_per_company(nightly, demo_db):

    from bjk_server.auth import set_tenant

    nightly()
    with Session(demo_db.app) as s:
        set_tenant(s, demo_id("company", "OTHER"))
        assert s.scalar(select(func.count()).select_from(PartMetrics)) == 0
