import threading
from datetime import timedelta

import pytest
from bjk_server import clock
from bjk_server.api.invites import token_hash
from bjk_server.db.models import Invite, User
from bjk_server.seed.demo import COMPANY_CODE
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .conftest import auth_header, build_client

URL = "/api/v1/auth/invites"


@pytest.fixture
def fresh(demo_db):
    demo_db.reseed()
    yield demo_db
    demo_db.reseed()


def _invite(client, role="worker"):
    res = client.post(URL, json={"role": role}, headers=auth_header("owner"))
    assert res.status_code == 201
    return res.json()


def _accept(client, token, name="정신입", pin="4321"):
    return client.post(f"{URL}/{token}/accept", json={"name": name, "pin": pin})


def test_create_invite_returns_token_and_join_url(client, fresh):
    body = _invite(client)
    assert body["token"].startswith("inv_")
    assert body["join_url"].endswith(f"/join/{body['token']}")
    assert body["role"] == "worker"
    with Session(fresh.admin) as s:
        invite = s.scalar(select(Invite))
        assert invite.token_hash == token_hash(body["token"])
        assert invite.token_hash != body["token"]
        assert invite.expires_at - invite.created_at == pytest.approx(
            timedelta(hours=72), abs=timedelta(seconds=5)
        )


def test_accept_registers_user_who_can_pin_login(client, fresh):
    token = _invite(client, role="manager")["token"]
    res = _accept(client, token, name="  정신입 ")
    assert res.status_code == 201
    body = res.json()
    assert body["company_code"] == COMPANY_CODE
    assert body["user"]["name"] == "정신입"
    assert body["user"]["role"] == "manager"
    me = client.get("/api/v1/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.json()["role"] == "manager"

    members = client.get(f"/api/v1/auth/companies/{COMPANY_CODE}/members").json()["items"]
    assert {"user_id": body["user"]["id"], "name": "정신입"} in members
    login = client.post(
        "/api/v1/auth/pin-login",
        json={"company_code": COMPANY_CODE, "user_id": body["user"]["id"], "pin": "4321"},
    )
    assert login.status_code == 200


def test_second_accept_is_410_used(client, fresh):
    token = _invite(client)["token"]
    assert _accept(client, token).status_code == 201
    res = _accept(client, token, name="두번째")
    assert res.status_code == 410
    assert res.json()["code"] == "INVITE_EXPIRED"
    assert res.json()["detail"]["reason"] == "used"


def test_expired_invite_is_410_expired(client, fresh, monkeypatch):
    token = _invite(client)["token"]
    later = clock.utcnow() + timedelta(hours=72, seconds=1)
    monkeypatch.setattr(clock, "utcnow", lambda: later)
    res = _accept(client, token)
    assert res.status_code == 410
    assert res.json()["detail"]["reason"] == "expired"


def test_unknown_token_is_404(client, fresh):
    assert _accept(client, "inv_nope").status_code == 404


@pytest.mark.parametrize(
    ("name", "pin"), [("정신입", "12a4"), ("정신입", "12345"), ("   ", "1234")]
)
def test_invalid_accept_input_is_400(client, fresh, name, pin):
    token = _invite(client)["token"]
    assert _accept(client, token, name=name, pin=pin).status_code == 400


def test_concurrent_accept_creates_one_user(fresh):
    token = _invite(build_client(fresh))["token"]
    results: list[int] = []
    barrier = threading.Barrier(4)

    def worker(i):
        c = build_client(fresh)
        barrier.wait()
        results.append(_accept(c, token, name=f"동시{i}").status_code)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == [201, 410, 410, 410]
    with Session(fresh.admin) as s:
        assert s.scalar(select(func.count()).where(User.name.like("동시%"))) == 1


@pytest.mark.parametrize("role", ["owner", "admin"])
def test_owner_role_cannot_be_invited(client, role):
    assert client.post(URL, json={"role": role}, headers=auth_header("owner")).status_code == 400


@pytest.mark.parametrize("user", ["manager", "worker"])
def test_only_owner_creates_invites(client, user):
    res = client.post(URL, json={"role": "worker"}, headers=auth_header(user))
    assert res.status_code == 403
