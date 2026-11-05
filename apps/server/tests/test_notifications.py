"""알림 저장·목록·읽음 (API 명세서 NOT-01·02, 기능명세서 F-NOTI-03)."""

import uuid
from datetime import UTC, datetime

import pytest
from bjk_server import clock
from bjk_server.api import notifications as api
from bjk_server.auth import set_tenant
from bjk_server.db.models import Notification
from bjk_server.notify.service import notify, release_at
from bjk_server.seed.demo import COMPANY_CODE, demo_id
from sqlalchemy import select
from sqlalchemy.orm import Session

from .conftest import auth_header

COMPANY = demo_id("company", COMPANY_CODE)
MANAGER = demo_id("user", "manager")
WORKER = demo_id("user", "worker")
QUIET = {"start": "21:00", "end": "07:00"}
# 2026-11-05 10:00 KST
NOW = datetime(2026, 11, 5, 1, 0, tzinfo=UTC)


def kst(day, hour, minute=0):
    return datetime(2026, 11, day, hour, minute, tzinfo=clock.KST)


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (kst(5, 10), kst(5, 10)),
        (kst(5, 21), kst(6, 7)),
        (kst(5, 23, 30), kst(6, 7)),
        (kst(6, 6, 59), kst(6, 7)),
        (kst(6, 7), kst(6, 7)),
    ],
)
def test_release_at_moves_quiet_hours_to_end(now, expected):
    assert release_at(now, QUIET) == expected


def test_release_at_same_day_range_and_disabled():
    assert release_at(kst(5, 13), {"start": "12:00", "end": "14:00"}) == kst(5, 14)
    assert release_at(kst(5, 23), {"start": "00:00", "end": "00:00"}) == kst(5, 23)


def _notify(demo_db, now=NOW, users=(MANAGER,), key="review_urgent:rv-1"):
    with Session(demo_db.app) as s, s.begin():
        set_tenant(s, COMPANY)
        return notify(
            s,
            COMPANY,
            users,
            "review_urgent",
            "긴급: 볼베어링 6205ZZ 발주 마감 11/9",
            now,
            target=("review", uuid.UUID(int=1)),
            dedupe_key=key,
        )


@pytest.fixture
def fixed_now(monkeypatch):
    monkeypatch.setattr(api.clock, "utcnow", lambda: NOW)


def test_same_event_notifies_once_per_user(demo_db):
    demo_db.reseed()
    assert len(_notify(demo_db, users=(MANAGER, WORKER))) == 2
    assert _notify(demo_db, users=(MANAGER, WORKER)) == []
    assert len(_notify(demo_db, key="review_urgent:rv-1:d-2")) == 1


def test_list_shows_own_sent_notifications_with_unread(client, demo_db, fixed_now):
    demo_db.reseed()
    _notify(demo_db, users=(MANAGER, WORKER))
    # 조용한 시간(23:00)에 생겨 다음 날 07:00로 미뤄진 알림은 아직 안 보인다
    _notify(demo_db, now=kst(5, 23), key="later")

    body = client.get("/api/v1/notifications", headers=auth_header("manager")).json()

    assert body["unread"] == 1 and body["next_cursor"] is None
    [item] = body["items"]
    assert item["kind"] == "review_urgent" and item["read"] is False
    assert item["target"] == {"type": "review", "id": str(uuid.UUID(int=1))}
    assert item["channels"] == ["push", "in_app"]
    assert item["sent_at"] == "2026-11-05T10:00:00+09:00"


def test_list_pages_by_cursor(client, demo_db, fixed_now):
    demo_db.reseed()
    for i in range(3):
        _notify(demo_db, now=kst(5, 8 + i), key=f"k{i}")
    first = client.get("/api/v1/notifications?limit=2", headers=auth_header("manager")).json()
    assert [i["sent_at"][11:13] for i in first["items"]] == ["10", "09"]
    second = client.get(
        f"/api/v1/notifications?limit=2&cursor={first['next_cursor']}",
        headers=auth_header("manager"),
    ).json()
    assert [i["sent_at"][11:13] for i in second["items"]] == ["08"]
    assert second["next_cursor"] is None


def test_read_marks_once_and_hides_other_users(client, demo_db, fixed_now):
    demo_db.reseed()
    [mine] = _notify(demo_db)
    [theirs] = _notify(demo_db, users=(WORKER,), key="other")

    res = client.post(f"/api/v1/notifications/{mine}/read", headers=auth_header("manager"))
    assert res.status_code == 200 and res.json()["read"] is True
    again = client.post(f"/api/v1/notifications/{mine}/read", headers=auth_header("manager"))
    assert again.status_code == 200
    other = client.post(f"/api/v1/notifications/{theirs}/read", headers=auth_header("manager"))
    assert other.status_code == 404

    body = client.get("/api/v1/notifications", headers=auth_header("manager")).json()
    assert body["unread"] == 0
    with Session(demo_db.admin) as s:
        assert s.get(Notification, theirs).read_at is None


def test_other_company_notifications_are_invisible(demo_db):
    demo_db.reseed()
    _notify(demo_db)
    with Session(demo_db.app) as s, s.begin():
        set_tenant(s, uuid.uuid4())
        assert s.scalars(select(Notification)).all() == []
