"""오늘 활동 목록·채팅 인박스 (W-01, F-AUDIT-06, #275)."""

from concurrent.futures import Executor, Future
from datetime import datetime, timedelta

import pytest
from bjk_server import clock
from bjk_server.reviews import drafts
from bjk_server.reviews.service import ReviewRunner
from bjk_server.seed.demo import demo_id
from sqlalchemy.orm import sessionmaker

from .conftest import auth_header
from .test_count_requests import NOW, _request, flags  # noqa: F401

P6205 = demo_id("part", "6205")


class _Inline(Executor):
    def submit(self, fn, /, *args, **kwargs):
        future: Future = Future()
        future.set_result(fn(*args, **kwargs))
        return future


@pytest.fixture(autouse=True)
def _clock(monkeypatch, demo_db):
    monkeypatch.setattr(clock, "utcnow", lambda: NOW)
    # 출고로 생긴 재고 부족 초안 검토를 커밋 직후 같은 스레드에서 끝낸다. 백그라운드로 두면
    # 다음 테스트의 시드 초기화(TRUNCATE)와 겹쳐 교착 상태가 난다.
    scope = sessionmaker(demo_db.app, expire_on_commit=False).begin
    monkeypatch.setattr(drafts, "request_runner", lambda db: ReviewRunner(scope, None, _Inline()))


def _activity(client, user="manager"):
    return client.get("/api/v1/activity/today", headers=auth_header(user))


def _inbox(client, user="worker"):
    return client.get("/api/v1/chat/inbox", headers=auth_header(user)).json()["items"]


def _answer(client, request_id, qty):
    return client.post(
        f"/api/v1/count-requests/{request_id}/answer",
        json={"counted_qty": qty},
        headers=auth_header("worker"),
    )


def test_activity_lists_today_events_newest_first(client, flags):  # noqa: F811
    request_id = _request(client, flags["오링 P-20"]).json()["count_request_id"]
    assert _answer(client, request_id, 1040).status_code == 200
    form = {"client_message_id": "act-1", "type": "OUT", "part_id": str(P6205), "qty": 2}
    client.post("/api/v1/chat/entries", json=form, headers=auth_header("worker"))

    res = _activity(client)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["date"] == "2026-11-04"
    texts = {i["kind"]: i["text"] for i in body["items"]}
    assert texts["audit_requested"] == "오링 P-20 실사 요청 → 이현장"
    assert texts["audit_resolved"] == "오링 P-20 실사 종료 — 이상 없음"
    assert "볼베어링 6205ZZ 출고 -2개" in [i["text"] for i in body["items"]]
    ids = {i["id"] for i in body["items"]}
    assert {f"aq-{request_id}", f"ar-{request_id}"} <= ids
    start = datetime(2026, 11, 4, tzinfo=clock.KST)
    times = [datetime.fromisoformat(i["at"]) for i in body["items"]]
    assert all(t >= start for t in times)
    assert times == sorted(times, reverse=True)
    assert len(body["items"]) <= 100


def test_worker_cannot_see_activity(client, flags):  # noqa: F811
    assert _activity(client, "worker").status_code == 403


def test_inbox_shows_own_count_request_without_book_qty(client, flags):  # noqa: F811
    request_id = _request(client, flags["오링 P-20"]).json()["count_request_id"]
    items = _inbox(client)
    assert items == [
        {
            "id": request_id,
            "kind": "count_request",
            "text": "오링 P-20 지금 몇 개 있나요? 세어서 숫자만 보내 주세요.",
            "created_at": NOW.isoformat().replace("+00:00", "Z"),
            "count_request_id": request_id,
        }
    ]
    assert "1040" not in items[0]["text"]
    assert _inbox(client, "worker2") == []
    assert _answer(client, request_id, 1040).status_code == 200
    assert _inbox(client) == []


def test_scheduled_request_reaches_inbox_at_scheduled_time(client, flags, monkeypatch):  # noqa: F811
    for name in ["볼베어링 6205ZZ", "볼베어링 6204ZZ", "오링 P-20"]:
        _request(client, flags[name])
    assert len(_inbox(client)) == 2
    monkeypatch.setattr(clock, "utcnow", lambda: NOW + timedelta(days=1))
    items = _inbox(client)
    assert len(items) == 3
    assert items[-1]["text"].startswith("오링 P-20")
