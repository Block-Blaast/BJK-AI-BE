"""운영 시연용 외부 충격 스위치 (#303). 처리는 DEV-02와 같고 개발 모드가 아니어도 열린다."""

from datetime import UTC, datetime, timedelta

import pytest
from bjk_server import clock
from bjk_server.api import api_router
from bjk_server.db.models import PartMetrics
from bjk_server.jobs import registry  # noqa: F401
from bjk_server.jobs.runner import run_job
from bjk_server.seed.demo import demo_id
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.orm import Session

from .conftest import auth_header

NIGHTLY = datetime(2026, 11, 3, 18, 0, tzinfo=UTC)  # 2026-11-04 03:00 KST
NOW = NIGHTLY + timedelta(hours=6)
URL = "/api/v1/scenarios"


@pytest.fixture
def computed(demo_db, monkeypatch):
    demo_db.reseed()
    assert run_job(demo_db.app, "nightly", "manual", now=NIGHTLY).status == "ok"
    monkeypatch.setattr(clock, "utcnow", lambda: NOW)


def _bearing_r_lead(demo_db) -> float:
    with Session(demo_db.admin) as s:
        return s.scalar(
            select(PartMetrics.r_lead)
            .where(PartMetrics.part_id == demo_id("part", "6205"))
            .order_by(PartMetrics.computed_at.desc())
            .limit(1)
        )


def _switch(client, enabled, user="owner"):
    return client.post(
        f"{URL}/external-shock", json={"enabled": enabled}, headers=auth_header(user)
    )


def test_route_is_not_dev_only():
    """운영(개발 모드 아님)에도 붙는 /api/v1 라우터에 있다."""
    app = FastAPI()
    app.include_router(api_router)
    paths = set(app.openapi()["paths"])
    assert {"/api/v1/scenarios", "/api/v1/scenarios/external-shock"} <= paths


def test_owner_switches_shock_on_and_off(client, demo_db, computed):
    before = _bearing_r_lead(demo_db)
    assert client.get(URL, headers=auth_header("owner")).json() == {"external_shock": False}

    on = _switch(client, True)
    assert on.status_code == 200, on.text
    assert (on.json()["indicator"], on.json()["r"]) == ("FREIGHT", 3.0)
    assert _bearing_r_lead(demo_db) == 3.0
    assert client.get(URL, headers=auth_header("owner")).json() == {"external_shock": True}
    status = client.get("/api/v1/external/status", headers=auth_header("owner")).json()
    assert {i["code"]: i["level"] for i in status["indicators"]}["FREIGHT"] == "high"

    off = _switch(client, False).json()
    assert off["r"] == pytest.approx(before)
    assert _bearing_r_lead(demo_db) == pytest.approx(before)


@pytest.mark.parametrize("user", ["manager", "worker"])
def test_only_owner(client, computed, user):
    assert _switch(client, True, user=user).status_code == 403
    assert client.get(URL, headers=auth_header(user)).status_code == 403
