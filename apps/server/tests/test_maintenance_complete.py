from datetime import UTC, datetime, timedelta

import pytest
from bjk_server import clock
from bjk_server.db.models import AuditFlag, Maintenance
from bjk_server.jobs import registry  # noqa: F401
from bjk_server.jobs.runner import run_job
from bjk_server.seed.demo import demo_id
from sqlalchemy import select
from sqlalchemy.orm import Session

from .conftest import auth_header

NOW = datetime(2026, 11, 20, 6, 0, tzinfo=UTC)  # 2026-11-20 15:00 KST
UPCOMING = demo_id("maintenance", "eq3:16")  # 3호기 2026-11-20
DONE = demo_id("maintenance", "eq3:-3")


@pytest.fixture
def fresh(demo_db, monkeypatch):
    demo_db.reseed()
    monkeypatch.setattr(clock, "utcnow", lambda: NOW)


def _complete(client, mid, body=None, user="worker"):
    return client.post(f"/api/v1/maintenance/{mid}/complete", json=body, headers=auth_header(user))


def test_worker_completes_and_later_out_links(client, demo_db, fresh, monkeypatch):
    res = _complete(client, UPCOMING)
    assert res.status_code == 200, res.text
    assert res.json() == {"maintenance_id": str(UPCOMING), "completed_at": "2026-11-20T06:00:00Z"}
    with Session(demo_db.admin) as s:
        assert s.get(Maintenance, UPCOMING).completed_by == demo_id("user", "worker")

    # 완료 47시간 뒤 같은 설비 출고는 이 정비에 연결된다.
    later = NOW + timedelta(hours=47)
    body = {
        "client_message_id": "done-out",
        "type": "OUT",
        "part_id": str(demo_id("part", "6205")),
        "qty": 1,
        "equipment_id": str(demo_id("equipment", "eq3")),
    }
    monkeypatch.setattr(clock, "utcnow", lambda: later)
    out = client.post("/api/v1/chat/entries", json=body, headers=auth_header("worker")).json()
    assert out["movement"]["maintenance_id"] == str(UPCOMING)


def test_completion_record_drives_maintenance_audit(client, demo_db, fresh):
    _complete(client, UPCOMING, {"completed_at": "2026-11-20T10:00:00+09:00"})
    # 완료 48시간 뒤까지 필요 부품 출고가 없으면 장부 의심 (6205 4개, 오링 100개)
    assert run_job(demo_db.app, "nightly", "manual", now=NOW + timedelta(days=3)).status == "ok"
    with Session(demo_db.admin) as s:
        flags = s.scalars(select(AuditFlag).where(AuditFlag.status == "open")).all()
    mismatched = {
        f.part_id
        for f in flags
        for hit in [{"rule": f.rule, "evidence": f.evidence}, *f.related]
        if hit["rule"] == "MAINTENANCE_OUT_MISMATCH"
        and hit["evidence"]["maintenance_id"] == str(UPCOMING)
    }
    assert mismatched == {demo_id("part", "6205"), demo_id("part", "p20")}


def test_already_completed_is_409(client, fresh):
    res = _complete(client, DONE)
    assert res.status_code == 409
    assert res.json()["detail"]["status"] == "completed"


@pytest.mark.parametrize(
    "completed_at", ["2026-11-21T00:00:00+09:00", "2026-11-20T10:00:00"], ids=["future", "naive"]
)
def test_invalid_completed_at_is_400(client, fresh, completed_at):
    assert _complete(client, UPCOMING, {"completed_at": completed_at}).status_code == 400


def test_unknown_maintenance_is_404(client, fresh):
    assert _complete(client, demo_id("maintenance", "none")).status_code == 404
