from datetime import UTC, datetime, timedelta

import httpx
from bjk_server import clock
from bjk_server.ai.client import get_ai_client
from bjk_server.db.models import ExternalIndicator
from bjk_server.db.session import get_db
from bjk_server.jobs import registry  # noqa: F401
from bjk_server.jobs.runner import run_job
from sqlalchemy import update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from .ai_fakes import FakeAi

URL = "/api/v1/health"
NOW = datetime(2026, 11, 3, 18, 0, tzinfo=UTC)


def test_health_before_any_batch(client, demo_db):
    demo_db.reseed()
    res = client.get(URL)
    assert res.status_code == 200
    assert res.json() == {
        "db": "ok",
        "llm": "not_configured",
        "last_batch": {"nightly": None, "status": None},
        "external_indicators": {"updated_at": None, "stale": True},
    }


def test_health_after_nightly(client, demo_db, monkeypatch):
    demo_db.reseed()
    assert run_job(demo_db.app, "nightly", "manual", now=NOW).status == "ok"
    monkeypatch.setattr(clock, "utcnow", lambda: datetime.now(UTC))
    body = client.get(URL).json()
    assert body["last_batch"]["status"] == "ok"
    assert datetime.fromisoformat(body["last_batch"]["nightly"]) == NOW
    assert body["external_indicators"]["stale"] is False


def test_indicators_older_than_24_hours_are_stale(client, demo_db, monkeypatch):
    demo_db.reseed()
    run_job(demo_db.app, "nightly", "manual", now=NOW)
    with Session(demo_db.admin) as s, s.begin():
        s.execute(
            update(ExternalIndicator).values(updated_at=datetime.now(UTC) - timedelta(hours=25))
        )
    assert client.get(URL).json()["external_indicators"]["stale"] is True


def test_db_failure_is_503(client):
    class BrokenSession:
        def execute(self, *_):
            raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    client.app.dependency_overrides[get_db] = lambda: BrokenSession()
    res = client.get(URL)
    assert res.status_code == 503
    assert res.json() == {
        "db": "error",
        "llm": "not_configured",
        "last_batch": None,
        "external_indicators": None,
    }


def test_llm_follows_ai_health(client, demo_db):
    ai = FakeAi()
    client.app.dependency_overrides[get_ai_client] = ai.client
    assert client.get(URL).json()["llm"] == "ok"
    ai.llm = "not_configured"
    assert client.get(URL).json()["llm"] == "not_configured"


def test_llm_error_when_ai_unreachable(client, demo_db):
    ai = FakeAi(fail=httpx.ConnectError("connection refused"))
    client.app.dependency_overrides[get_ai_client] = ai.client
    assert client.get(URL).json()["llm"] == "error"


def test_health_is_public(client):
    assert client.get(URL).status_code == 200
