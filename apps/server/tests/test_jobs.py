from datetime import UTC, datetime

import pytest
from bjk_server.auth import set_tenant
from bjk_server.config import get_settings
from bjk_server.db.models import JobRun, Part
from bjk_server.jobs import runner
from bjk_server.jobs.__main__ import main as jobs_cli
from bjk_server.main import create_app
from bjk_server.seed.demo import demo_id
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from .conftest import auth_header

NOW = datetime(2026, 11, 3, 18, 0, tzinfo=UTC)


@pytest.fixture
def registry(monkeypatch):
    jobs = {}
    monkeypatch.setattr(runner, "REGISTRY", jobs)
    return jobs


def _runs(demo_db, name):
    with Session(demo_db.admin) as s:
        return s.scalars(
            select(JobRun).where(JobRun.name == name).order_by(JobRun.started_at)
        ).all()


def test_successful_job_is_recorded(demo_db, registry):
    registry["nightly"] = lambda session, now: {"parts_computed": 6, "now": now.isoformat()}
    result = runner.run_job(demo_db.app, "nightly", "schedule", now=NOW)
    assert result.status == "ok"
    assert result.summary["parts_computed"] == 6
    run = _runs(demo_db, "nightly")[-1]
    assert (run.status, run.trigger, run.started_at) == ("ok", "schedule", NOW)


def test_unimplemented_job_is_skipped(demo_db, registry):
    result = runner.run_job(demo_db.app, "briefing", "manual")
    assert (result.status, result.summary) == ("skipped", {"reason": "not_implemented"})


def test_failed_job_rolls_back_its_work_and_records_error(demo_db, registry):
    def broken(session, now):
        set_tenant(session, demo_id("company", "HS7F3K"))
        session.get(Part, demo_id("part", "6205")).name = "바뀌면 안 됨"
        session.flush()
        raise RuntimeError("boom")

    registry["order-check"] = broken
    result = runner.run_job(demo_db.app, "order-check", "schedule")
    assert result.status == "error"
    assert result.error == "RuntimeError: boom"
    with Session(demo_db.admin) as s:
        assert s.get(Part, demo_id("part", "6205")).name == "볼베어링 6205ZZ"
    assert _runs(demo_db, "order-check")[-1].status == "error"


def test_concurrent_run_is_skipped(demo_db, registry):
    registry["weekly-merge"] = lambda session, now: {}
    with demo_db.admin.connect() as other, other.begin():
        other.execute(text("SELECT pg_advisory_xact_lock(hashtext('job:weekly-merge'))"))
        result = runner.run_job(demo_db.app, "weekly-merge", "schedule")
    assert (result.status, result.summary) == ("skipped", {"reason": "already_running"})


def test_unknown_job_name_is_rejected(demo_db):
    with pytest.raises(ValueError):
        runner.run_job(demo_db.app, "nope", "manual")


def test_cli_exit_code_follows_status(demo_db, registry, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", demo_db.app.url.render_as_string(hide_password=False))
    get_settings.cache_clear()
    try:
        registry["nightly"] = lambda session, now: {}
        assert jobs_cli(["nightly"]) == 0
        registry["nightly"] = lambda session, now: 1 / 0
        assert jobs_cli(["nightly"]) == 1
    finally:
        get_settings.cache_clear()


def test_dev_api_runs_job(client, registry):
    registry["nightly"] = lambda session, now: {"parts_computed": 6}
    res = client.post("/api/v1/dev/jobs/nightly/run", headers=auth_header("owner"))
    assert res.status_code == 200
    body = res.json()
    assert (body["job"], body["status"], body["parts_computed"]) == ("nightly", "ok", 6)
    assert {"started_at", "finished_at"} <= set(body)


def test_dev_api_rejects_unknown_name_and_non_owner(client):
    assert client.post("/api/v1/dev/jobs/nope/run", headers=auth_header("owner")).status_code == 400
    assert (
        client.post("/api/v1/dev/jobs/nightly/run", headers=auth_header("manager")).status_code
        == 403
    )


def test_dev_api_absent_outside_dev(monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("JWT_SECRET", "p" * 40)
    get_settings.cache_clear()
    try:
        assert TestClient(create_app()).post("/api/v1/dev/jobs/nightly/run").status_code == 404
    finally:
        get_settings.cache_clear()


def test_job_session_without_tenant_sees_no_company_rows(demo_db, registry):
    """배치도 RLS 안에서 돈다. 회사를 지정하지 않으면 업무 테이블이 보이지 않는다."""
    seen = {}

    def peek(session, now):
        seen["parts"] = session.scalar(select(func.count()).select_from(Part))
        seen["companies"] = runner.company_ids(session)
        return {}

    registry["nightly"] = peek
    assert runner.run_job(demo_db.app, "nightly", "manual").status == "ok"
    assert seen == {"parts": 0, "companies": [demo_id("company", "HS7F3K")]}
