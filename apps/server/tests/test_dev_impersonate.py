import pytest
from bjk_server.config import get_settings
from bjk_server.db.models import User
from bjk_server.main import create_app
from bjk_server.security import decode_token
from bjk_server.seed.demo import demo_id
from sqlalchemy import update
from sqlalchemy.orm import Session

from .conftest import auth_header

URL = "/api/v1/dev/impersonate"


@pytest.mark.parametrize(("role", "name"), [("worker", "이현장"), ("manager", "최관리")])
def test_owner_gets_demo_account_token(client, role, name):
    res = client.post(URL, json={"role": role}, headers=auth_header("owner"))
    assert res.status_code == 200
    body = res.json()
    assert body["user"] == {"id": str(demo_id("user", role)), "name": name, "role": role}
    assert decode_token(body["access_token"], "access").role == role


def test_falls_back_to_first_account_of_role(client, demo_db):
    with Session(demo_db.admin) as s, s.begin():
        s.execute(update(User).where(User.id == demo_id("user", "worker")).values(active=False))
    try:
        res = client.post(URL, json={"role": "worker"}, headers=auth_header("owner"))
        assert res.json()["user"]["name"] == "박정비"
    finally:
        demo_db.reseed()


def test_non_owner_is_forbidden(client):
    res = client.post(URL, json={"role": "owner"}, headers=auth_header("manager"))
    assert res.status_code == 403


def test_unknown_role_is_400(client):
    res = client.post(URL, json={"role": "admin"}, headers=auth_header("owner"))
    assert res.status_code == 400


def test_route_absent_outside_dev(monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("JWT_SECRET", "p" * 40)
    get_settings.cache_clear()
    try:
        assert TestClient(create_app()).post(URL, json={"role": "worker"}).status_code == 404
    finally:
        get_settings.cache_clear()
