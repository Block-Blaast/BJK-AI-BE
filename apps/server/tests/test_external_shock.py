from datetime import UTC, datetime, timedelta

import pytest
from bjk_server import clock
from bjk_server.db.models import PartMetrics
from bjk_server.jobs import registry  # noqa: F401
from bjk_server.jobs.runner import run_job
from bjk_server.seed.demo import demo_id
from sqlalchemy import select
from sqlalchemy.orm import Session

from .conftest import auth_header

NIGHTLY = datetime(2026, 11, 3, 18, 0, tzinfo=UTC)  # 2026-11-04 03:00 KST
NOW = NIGHTLY + timedelta(hours=6)
URL = "/api/v1/dev/scenarios/external-shock"


@pytest.fixture
def computed(demo_db, monkeypatch):
    demo_db.reseed()
    assert run_job(demo_db.app, "nightly", "manual", now=NIGHTLY).status == "ok"
    monkeypatch.setattr(clock, "utcnow", lambda: NOW)


def _bearing(demo_db) -> PartMetrics:
    with Session(demo_db.admin) as s:
        return s.scalar(
            select(PartMetrics)
            .where(PartMetrics.part_id == demo_id("part", "6205"))
            .order_by(PartMetrics.computed_at.desc())
            .limit(1)
        )


def _switch(client, enabled, user="owner"):
    return client.post(URL, json={"enabled": enabled}, headers=auth_header(user))


def test_shock_fixes_freight_risk_and_recomputes(client, demo_db, computed):
    before = _bearing(demo_db)
    assert before.r_lead < 3

    res = _switch(client, True)
    assert res.status_code == 200, res.text
    body = res.json()
    assert (body["enabled"], body["indicator"], body["r"], body["parts_computed"]) == (
        True,
        "FREIGHT",
        3.0,
        6,
    )
    shocked = _bearing(demo_db)
    assert (shocked.r_lead, shocked.external_level) == (3.0, "high")
    # 수입 의존 부품의 납기가 늘어난다: 7일 × (1 + 0.25 × 3) = 12.25 → 13일
    assert shocked.lt90 > before.lt90
    # 운임에 연결되지 않은 볼트는 그대로
    with Session(demo_db.admin) as s:
        bolt = s.scalar(
            select(PartMetrics.r_lead).where(PartMetrics.part_id == demo_id("part", "m820"))
        )
    assert bolt == 0

    # 새벽 배치도 스위치를 따른다.
    assert run_job(demo_db.app, "nightly", "manual", now=NOW).status == "ok"
    assert _bearing(demo_db).r_lead == 3.0

    off = _switch(client, False).json()
    assert off["r"] == pytest.approx(before.r_lead)
    restored = _bearing(demo_db)
    assert (restored.r_lead, restored.lt90) == (pytest.approx(before.r_lead), before.lt90)


def test_only_owner_can_switch(client, computed):
    assert _switch(client, True, user="manager").status_code == 403
