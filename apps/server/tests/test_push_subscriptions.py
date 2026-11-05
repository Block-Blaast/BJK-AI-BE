"""웹 푸시 구독 저장·조회·해지 (API 명세서 NOT-04)."""

import uuid

import pytest
from bjk_server.auth import set_tenant
from bjk_server.config import get_settings
from bjk_server.db.models import PushSubscription
from bjk_server.seed.demo import demo_id
from sqlalchemy import select
from sqlalchemy.orm import Session

from .conftest import auth_header

URL = "/api/v1/push/subscriptions"
ENDPOINT = "https://web.push.apple.com/abc"


def _body(endpoint=ENDPOINT, p256dh="key-1", auth="auth-1"):
    return {"endpoint": endpoint, "keys": {"p256dh": p256dh, "auth": auth}}


@pytest.fixture
def fresh(demo_db):
    demo_db.reseed()


def test_subscribe_and_list_own(client, fresh):
    res = client.post(URL, json=_body(), headers=auth_header("worker"))
    assert res.status_code == 201
    assert res.json()["endpoint"] == ENDPOINT
    assert [s["endpoint"] for s in client.get(URL, headers=auth_header("worker")).json()] == [
        ENDPOINT
    ]
    assert client.get(URL, headers=auth_header("worker2")).json() == []


def test_resubscribe_same_endpoint_updates_keys_and_user(client, demo_db, fresh):
    first = client.post(URL, json=_body(), headers=auth_header("worker")).json()
    second = client.post(
        URL, json=_body(p256dh="key-2", auth="auth-2"), headers=auth_header("worker2")
    ).json()
    assert second["id"] == first["id"]
    with Session(demo_db.admin) as s:
        [row] = s.scalars(select(PushSubscription)).all()
        assert (row.user_id, row.p256dh, row.auth) == (
            demo_id("user", "worker2"),
            "key-2",
            "auth-2",
        )


@pytest.mark.parametrize(
    "body",
    [
        _body(endpoint="http://insecure.example/x"),
        _body(endpoint="not-a-url"),
        {"endpoint": ENDPOINT, "keys": {"p256dh": "", "auth": "a"}},
        {"endpoint": ENDPOINT},
    ],
)
def test_invalid_subscription_is_400(client, fresh, body):
    res = client.post(URL, json=body, headers=auth_header("worker"))
    assert res.status_code == 400
    assert res.json()["code"] == "VALIDATION_ERROR"


def test_unsubscribe_own_only(client, fresh):
    sub = client.post(URL, json=_body(), headers=auth_header("worker")).json()
    assert client.delete(f"{URL}/{sub['id']}", headers=auth_header("worker2")).status_code == 404
    assert client.delete(f"{URL}/{sub['id']}", headers=auth_header("worker")).status_code == 204
    assert client.get(URL, headers=auth_header("worker")).json() == []
    assert client.delete(f"{URL}/{uuid.uuid4()}", headers=auth_header("worker")).status_code == 404


def test_vapid_public_key(client, fresh, monkeypatch):
    res = client.get("/api/v1/push/vapid-key", headers=auth_header("worker"))
    assert res.json() == {"public_key": get_settings().vapid_public_key}
    monkeypatch.setattr(get_settings(), "vapid_public_key", "BPub")
    assert client.get("/api/v1/push/vapid-key", headers=auth_header("worker")).json() == {
        "public_key": "BPub"
    }


def test_other_company_cannot_see_subscriptions(client, demo_db, fresh):
    client.post(URL, json=_body(), headers=auth_header("worker"))
    with Session(demo_db.app) as s, s.begin():
        set_tenant(s, uuid.uuid4())
        assert s.scalars(select(PushSubscription)).all() == []
