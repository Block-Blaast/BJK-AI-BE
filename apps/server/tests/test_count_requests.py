import uuid
from datetime import UTC, datetime

import pytest
from bjk_server import clock
from bjk_server.db.models import Notification
from bjk_server.jobs import registry  # noqa: F401
from bjk_server.jobs.runner import run_job
from bjk_server.seed.demo import demo_id
from sqlalchemy import select
from sqlalchemy.orm import Session

from .conftest import auth_header

NIGHTLY = datetime(2026, 11, 3, 18, 0, tzinfo=UTC)  # 2026-11-04 03:00 KST
NOW = datetime(2026, 11, 4, 1, 0, tzinfo=UTC)  # 2026-11-04 10:00 KST
WORKER = demo_id("user", "worker")


@pytest.fixture
def flags(client, demo_db, monkeypatch):
    """새벽 배치로 의심 항목을 만들고 부품 이름 → 항목 ID를 돌려준다."""
    demo_db.reseed()
    assert run_job(demo_db.app, "nightly", "manual", now=NIGHTLY).status == "ok"
    monkeypatch.setattr(clock, "utcnow", lambda: NOW)
    items = client.get("/api/v1/audit-flags", headers=auth_header("manager")).json()["items"]
    return {i["part"]["name"]: i["id"] for i in items}


def _request(client, flag_id, assignee=WORKER, user="manager"):
    return client.post(
        f"/api/v1/audit-flags/{flag_id}/count-request",
        json={"assignee_id": str(assignee)},
        headers=auth_header(user),
    )


def _status(client, flag_id):
    items = client.get("/api/v1/audit-flags", headers=auth_header("manager")).json()["items"]
    return next(i["status"] for i in items if i["id"] == flag_id)


def test_blind_count_request_hides_book_qty(client, flags):
    flag_id = flags["오링 P-20"]
    res = _request(client, flag_id)
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["status"] == "sent"
    assert body["scheduled_for"] is None
    assert body["message_preview"] == "오링 P-20 지금 몇 개 있나요? 세어서 숫자만 보내 주세요."
    assert "1040" not in body["message_preview"]
    assert _status(client, flag_id) == "count_requested"


def test_same_flag_cannot_be_requested_twice(client, flags):
    flag_id = flags["오링 P-20"]
    assert _request(client, flag_id).status_code == 201
    res = _request(client, flag_id)
    assert res.status_code == 409
    assert res.json()["detail"] == {"status": "count_requested"}


def test_third_request_for_same_worker_is_scheduled_next_morning(client, flags):
    names = ["오링 P-20", "볼베어링 6205ZZ", "볼베어링 6204ZZ", "V벨트 A-42", "수용성 절삭유 20L"]
    bodies = [_request(client, flags[n]).json() for n in names]
    assert [b["status"] for b in bodies] == ["sent", "sent", "scheduled", "scheduled", "scheduled"]
    assert [b["scheduled_for"] for b in bodies[2:]] == [
        "2026-11-05T07:30:00+09:00",
        "2026-11-05T07:30:00+09:00",
        "2026-11-06T07:30:00+09:00",
    ]
    # 다른 작업자는 따로 센다.
    other = _request(client, flags["육각볼트 M8-20"], assignee=demo_id("user", "worker2"))
    assert other.json()["status"] == "sent"


def test_worker_cannot_request(client, flags):
    res = _request(client, flags["오링 P-20"], user="worker")
    assert res.status_code == 403


@pytest.mark.parametrize("target", ["flag", "assignee"])
def test_unknown_flag_or_assignee_is_404(client, flags, target):
    flag_id = uuid.uuid4() if target == "flag" else flags["오링 P-20"]
    assignee = uuid.uuid4() if target == "assignee" else WORKER
    res = _request(client, flag_id, assignee=assignee)
    assert res.status_code == 404
    assert res.json()["code"] == "NOT_FOUND"


def _count_notices(demo_db):
    with Session(demo_db.admin) as s:
        rows = s.scalars(
            select(Notification)
            .where(Notification.kind == "count_request")
            .order_by(Notification.sent_at)
        )
        return [(r.user_id, r.target_id, r.channels, r.title, r.sent_at) for r in rows]


def test_count_request_notifies_assignee_in_chat_and_push(client, demo_db, flags):
    body = _request(client, flags["오링 P-20"]).json()
    assert _count_notices(demo_db) == [
        (
            WORKER,
            uuid.UUID(body["count_request_id"]),
            ["chat", "push"],
            "오링 P-20 지금 몇 개 있나요? 세어서 숫자만 보내 주세요.",
            NOW,
        )
    ]
    items = client.get("/api/v1/notifications", headers=auth_header("worker")).json()["items"]
    assert [i["kind"] for i in items] == ["count_request"]


def test_scheduled_count_request_notice_shows_at_scheduled_time(client, demo_db, flags):
    names = ["오링 P-20", "볼베어링 6205ZZ", "볼베어링 6204ZZ"]
    for name in names:
        _request(client, flags[name])
    sent_at = [row[4] for row in _count_notices(demo_db)]
    assert sent_at == [NOW, NOW, datetime(2026, 11, 5, 7, 30, tzinfo=clock.KST)]
    items = client.get("/api/v1/notifications", headers=auth_header("worker")).json()["items"]
    assert len(items) == 2
