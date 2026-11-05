"""웹 푸시 발송 (API 명세서 NOT-04, #184)."""

import json
from concurrent.futures import Future
from datetime import UTC, datetime, timedelta

import pytest
from bjk_server.auth import set_tenant
from bjk_server.config import get_settings
from bjk_server.db.models import Notification, PushSubscription
from bjk_server.jobs import registry  # noqa: F401
from bjk_server.jobs.runner import run_job
from bjk_server.notify import push
from bjk_server.notify.service import notify
from bjk_server.seed.demo import COMPANY_CODE, demo_id
from sqlalchemy import select
from sqlalchemy.orm import Session

COMPANY = demo_id("company", COMPANY_CODE)
OWNER = demo_id("user", "owner")
MANAGER = demo_id("user", "manager")
NOW = datetime(2026, 11, 5, 1, 0, tzinfo=UTC)  # 10:00 KST
QUIET_NOW = datetime(2026, 11, 5, 13, 0, tzinfo=UTC)  # 22:00 KST, 조용한 시간


class FakePushServer:
    """endpoint별 응답 상태. 받은 (endpoint, payload)를 남긴다."""

    def __init__(self, statuses=None):
        self.statuses = statuses or {}
        self.received = []

    def __call__(self, sub, payload):
        self.received.append((sub.endpoint, json.loads(payload)))
        return self.statuses.get(sub.endpoint, 201)


class _Inline:
    def submit(self, fn, *args):
        future = Future()
        future.set_result(fn(*args))
        return future


@pytest.fixture
def fresh(demo_db):
    demo_db.reseed()
    with Session(demo_db.admin) as s, s.begin():
        for user, name in ((OWNER, "phone"), (OWNER, "pc"), (MANAGER, "m")):
            s.add(
                PushSubscription(
                    company_id=COMPANY,
                    user_id=user,
                    endpoint=f"https://push.test/{name}",
                    p256dh="p",
                    auth="a",
                )
            )
    yield demo_db
    demo_db.reseed()


@pytest.fixture
def server(monkeypatch):
    """VAPID 키가 있는 설정과 가짜 푸시 서버. 커밋 직후 발송은 같은 스레드에서 돈다."""
    fake = FakePushServer()
    monkeypatch.setattr(get_settings(), "vapid_private_key", "test-key")
    monkeypatch.setattr(push, "default_sender", lambda: fake)
    monkeypatch.setattr(push, "_executor", _Inline())
    return fake


def _notify(db, now=NOW, users=(OWNER,), channels=("push", "in_app"), key="k1"):
    with Session(db.app) as s, s.begin():
        set_tenant(s, COMPANY)
        return notify(
            s,
            COMPANY,
            users,
            "review_urgent",
            "긴급: 볼베어링",
            now,
            channels=channels,
            dedupe_key=key,
        )


def _row(db, notification_id) -> Notification:
    with Session(db.admin) as s:
        return s.get(Notification, notification_id)


def _endpoints(db) -> set[str]:
    with Session(db.admin) as s:
        return set(s.scalars(select(PushSubscription.endpoint)))


def test_commit_sends_to_every_subscription_of_receiver(fresh, server, monkeypatch):
    monkeypatch.setattr(push.clock, "utcnow", lambda: NOW)
    [nid] = _notify(fresh)
    assert sorted(e for e, _ in server.received) == [
        "https://push.test/pc",
        "https://push.test/phone",
    ]
    payload = server.received[0][1]
    assert payload == {
        "notification_id": str(nid),
        "kind": "review_urgent",
        "title": "긴급: 볼베어링",
        "target": None,
    }
    assert _row(fresh, nid).pushed_at == NOW


def test_in_app_only_is_not_pushed(fresh, server):
    [nid] = _notify(fresh, channels=("in_app",))
    assert server.received == []
    assert _row(fresh, nid).pushed_at is None


def test_rollback_sends_nothing(fresh, server):
    with pytest.raises(RuntimeError), Session(fresh.app) as s, s.begin():
        set_tenant(s, COMPANY)
        notify(s, COMPANY, [OWNER], "review_urgent", "t", NOW, dedupe_key="rb")
        raise RuntimeError
    assert server.received == []


def test_expired_subscription_is_deleted_and_notification_kept(fresh, server, monkeypatch):
    monkeypatch.setattr(push.clock, "utcnow", lambda: NOW)
    server.statuses = {"https://push.test/phone": 410, "https://push.test/pc": 500}
    [nid] = _notify(fresh)
    assert "https://push.test/phone" not in _endpoints(fresh)
    assert "https://push.test/pc" in _endpoints(fresh)  # 일시 실패는 구독 유지
    row = _row(fresh, nid)
    assert row.pushed_at == NOW and row.read_at is None  # 앱 안 알림은 그대로


def test_quiet_hours_push_waits_for_job(fresh, server):
    [nid] = _notify(fresh, now=QUIET_NOW, key="quiet")
    assert server.received == []
    early = run_job(fresh.app, "push", "manual", now=QUIET_NOW + timedelta(hours=1))
    assert early.summary["notifications"] == 0
    morning = datetime(2026, 11, 5, 22, 0, tzinfo=UTC)  # 07:00 KST
    result = run_job(fresh.app, "push", "manual", now=morning)
    assert result.status == "ok", result.error
    assert result.summary == {"notifications": 1, "sent": 2, "failed": 0, "expired": 0}
    assert _row(fresh, nid).pushed_at == morning
    again = run_job(fresh.app, "push", "manual", now=morning + timedelta(minutes=10))
    assert again.summary["notifications"] == 0


def test_without_vapid_key_nothing_is_sent(fresh, monkeypatch):
    monkeypatch.setattr(get_settings(), "vapid_private_key", None)
    [nid] = _notify(fresh, key="nokey")
    assert _row(fresh, nid).pushed_at is None
    result = run_job(fresh.app, "push", "manual", now=NOW)
    assert result.summary == {"skipped": "vapid_not_configured"}


def test_dispatch_only_touches_current_company(fresh, server):
    [nid] = _notify(fresh, now=QUIET_NOW, key="other")
    with Session(fresh.app) as s, s.begin():
        set_tenant(s, demo_id("company", "OTHER"))
        result = push.dispatch(s, server, QUIET_NOW + timedelta(days=1))
    assert result.notifications == 0
    assert _row(fresh, nid).pushed_at is None
