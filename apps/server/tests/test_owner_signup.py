import re

import pytest
from bjk_server.api import auth as auth_api
from bjk_server.company import CODE_ALPHABET
from bjk_server.db.models import Category, CompanySettings
from bjk_server.defaults import DEFAULT_CATEGORIES, DEFAULT_SETTINGS
from bjk_server.seed.demo import USERS
from sqlalchemy import select
from sqlalchemy.orm import Session

from .conftest import auth_header

URL = "/api/v1/auth/owner/signup"


def _body(**overrides):
    return {
        "company_name": "대구정밀",
        "name": "최사장",
        "email": "owner@daegu.kr",
        "password": "password1",
    } | overrides


@pytest.fixture
def fresh(demo_db):
    demo_db.reseed()
    yield demo_db
    demo_db.reseed()


def test_signup_creates_company_owner_and_tokens(client, fresh):
    res = client.post(URL, json=_body())
    assert res.status_code == 201
    body = res.json()
    assert body["user"]["role"] == "owner"
    assert body["user"]["name"] == "최사장"
    assert body["company"]["name"] == "대구정밀"
    assert re.fullmatch(f"[{CODE_ALPHABET}]{{6}}", body["company"]["code"])
    assert body["expires_in"] == 900

    me = client.get("/api/v1/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200
    assert me.json()["company"] == body["company"]
    assert me.json()["role"] == "owner"


def test_signup_seeds_default_settings_and_categories(client, fresh):
    company_id = client.post(URL, json=_body()).json()["company"]["id"]
    with Session(fresh.admin) as s:
        settings = s.get(CompanySettings, company_id)
        assert settings.review == DEFAULT_SETTINGS["review"]
        names = s.scalars(select(Category.name).where(Category.company_id == company_id))
        assert sorted(names) == sorted(c[1] for c in DEFAULT_CATEGORIES)


def test_new_owner_can_log_in_with_case_insensitive_email(client, fresh):
    client.post(URL, json=_body(email="  Owner@Daegu.KR "))
    res = client.post(
        "/api/v1/auth/login", json={"email": "owner@daegu.kr", "password": "password1"}
    )
    assert res.status_code == 200
    assert res.json()["user"]["name"] == "최사장"


def test_new_company_is_isolated(client, fresh):
    token = client.post(URL, json=_body()).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/v1/parts", headers=headers).json()["items"] == []
    seeded = client.get("/api/v1/parts", headers=auth_header("owner")).json()["items"]
    assert seeded


@pytest.mark.parametrize("email", ["owner@hanseo.kr", "OWNER@HANSEO.KR"])
def test_duplicate_email_is_409(client, fresh, email):
    assert any(u.email == "owner@hanseo.kr" for u in USERS)
    res = client.post(URL, json=_body(email=email))
    assert res.status_code == 409
    assert res.json()["code"] == "EMAIL_TAKEN"


@pytest.mark.parametrize(
    "overrides",
    [
        {"password": "short7!"},
        {"email": "not-an-email"},
        {"company_name": ""},
        {"name": ""},
        {"name": "   "},
    ],
)
def test_invalid_input_is_400(client, fresh, overrides):
    res = client.post(URL, json=_body(**overrides))
    assert res.status_code == 400
    assert res.json()["code"] == "VALIDATION_ERROR"


def test_signup_rate_limit(client, fresh, monkeypatch):
    monkeypatch.setattr(auth_api, "SIGNUPS_PER_HOUR", 2)
    for i in range(2):
        assert client.post(URL, json=_body(email=f"o{i}@daegu.kr")).status_code == 201
    res = client.post(URL, json=_body(email="o9@daegu.kr"))
    assert res.status_code == 429
    assert "Retry-After" in res.headers
