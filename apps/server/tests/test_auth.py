import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
import pytest
from bjk_server.auth import CurrentUser, require_role
from bjk_server.config import get_settings
from bjk_server.main import create_app
from bjk_server.security import (
    ALGORITHM,
    TokenClaims,
    create_access_token,
    create_refresh_token,
    hash_secret,
    verify_secret,
)
from fastapi import Depends
from fastapi.testclient import TestClient

USER, COMPANY = uuid.uuid4(), uuid.uuid4()


@pytest.fixture
def client() -> TestClient:
    app = create_app()

    @app.get("/_test/me")
    def me(user: CurrentUser):
        return {"user_id": str(user.user_id), "role": user.role}

    @app.get("/_test/manager")
    def manager(user: Annotated[TokenClaims, Depends(require_role("manager"))]):
        return {"ok": True}

    return TestClient(app)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_valid_access_token_passes(client):
    res = client.get("/_test/me", headers=_auth(create_access_token(USER, COMPANY, "worker")))
    assert res.status_code == 200
    assert res.json() == {"user_id": str(USER), "role": "worker"}


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Basic abc"},
        _auth("not-a-token"),
        _auth(create_refresh_token(USER, COMPANY, "owner")),
    ],
    ids=["missing", "wrong-scheme", "garbage", "refresh-token"],
)
def test_missing_or_invalid_token_is_401(client, headers):
    res = client.get("/_test/me", headers=headers)
    assert res.status_code == 401
    assert res.json()["code"] == "UNAUTHORIZED"


def test_expired_token_is_401(client):
    past = datetime.now(UTC) - timedelta(minutes=1)
    token = jwt.encode(
        {
            "user_id": str(USER),
            "company_id": str(COMPANY),
            "role": "owner",
            "type": "access",
            "jti": "x",
            "exp": past,
        },
        get_settings().jwt_secret,
        algorithm=ALGORITHM,
    )
    assert client.get("/_test/me", headers=_auth(token)).status_code == 401


def test_token_signed_with_other_secret_is_401(client):
    token = jwt.encode(
        {"user_id": str(USER), "company_id": str(COMPANY), "role": "owner", "type": "access"},
        "another-secret-that-is-long-enough-32b",
        algorithm=ALGORITHM,
    )
    assert client.get("/_test/me", headers=_auth(token)).status_code == 401


@pytest.mark.parametrize(("role", "status"), [("worker", 403), ("manager", 200), ("owner", 200)])
def test_require_role_minimum(client, role, status):
    res = client.get("/_test/manager", headers=_auth(create_access_token(USER, COMPANY, role)))
    assert res.status_code == status
    if status == 403:
        assert res.json()["code"] == "FORBIDDEN_ROLE"


def test_secret_hash_round_trip():
    hashed = hash_secret("1234")
    assert hashed != "1234"
    assert verify_secret(hashed, "1234")
    assert not verify_secret(hashed, "4321")
    assert not verify_secret(None, "1234")


def test_access_token_lifetime_is_15_minutes():
    token = create_access_token(USER, COMPANY, "owner")
    payload = jwt.decode(token, get_settings().jwt_secret, algorithms=[ALGORITHM])
    assert payload["exp"] - payload["iat"] == 15 * 60


def test_production_requires_real_secret(monkeypatch):
    from bjk_server.config import Settings

    monkeypatch.setenv("APP_ENV", "prod")
    with pytest.raises(ValueError, match="JWT_SECRET"):
        Settings()
    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    assert not Settings().is_dev
