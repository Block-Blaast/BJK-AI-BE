from datetime import UTC, datetime, timedelta

import jwt
import pytest
from bjk_server.config import get_settings
from bjk_server.db.models import User
from bjk_server.security import ALGORITHM, create_access_token, create_refresh_token, decode_token
from bjk_server.seed.demo import COMPANY_CODE, demo_id
from sqlalchemy import update
from sqlalchemy.orm import Session

URL = "/api/v1/auth/refresh"
OWNER, COMPANY = demo_id("user", "owner"), demo_id("company", COMPANY_CODE)


def test_refresh_issues_new_pair(client):
    old = create_refresh_token(OWNER, COMPANY, "owner")
    res = client.post(URL, json={"refresh_token": old})
    assert res.status_code == 200
    body = res.json()
    assert body["expires_in"] == 900
    assert decode_token(body["access_token"], "access").user_id == OWNER
    assert body["refresh_token"] != old


def test_refresh_uses_current_role(client, demo_db):
    with Session(demo_db.admin) as s, s.begin():
        s.execute(update(User).where(User.id == OWNER).values(role="manager"))
    try:
        res = client.post(
            URL, json={"refresh_token": create_refresh_token(OWNER, COMPANY, "owner")}
        )
        assert decode_token(res.json()["access_token"], "access").role == "manager"
    finally:
        demo_db.reseed()


def _expired_refresh() -> str:
    past = datetime.now(UTC) - timedelta(seconds=1)
    payload = {
        "user_id": str(OWNER),
        "company_id": str(COMPANY),
        "role": "owner",
        "type": "refresh",
        "jti": "x",
        "exp": past,
    }
    return jwt.encode(payload, get_settings().jwt_secret, algorithm=ALGORITHM)


@pytest.mark.parametrize(
    "token",
    [create_access_token(OWNER, COMPANY, "owner"), "garbage", _expired_refresh()],
    ids=["access-token", "garbage", "expired"],
)
def test_invalid_refresh_is_401(client, token):
    res = client.post(URL, json={"refresh_token": token})
    assert res.status_code == 401
    assert res.json()["code"] == "UNAUTHORIZED"


def test_inactive_user_cannot_refresh(client, demo_db):
    with Session(demo_db.admin) as s, s.begin():
        s.execute(update(User).where(User.id == OWNER).values(active=False))
    try:
        res = client.post(
            URL, json={"refresh_token": create_refresh_token(OWNER, COMPANY, "owner")}
        )
        assert res.status_code == 401
    finally:
        demo_db.reseed()
