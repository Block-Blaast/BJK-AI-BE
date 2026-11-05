import pytest
from bjk_server.security import decode_token
from bjk_server.seed.demo import COMPANY_CODE, demo_id

URL = "/api/v1/auth/login"


def test_owner_logs_in_with_email(client):
    res = client.post(URL, json={"email": "owner@hanseo.kr", "password": "demo-owner-1234"})
    assert res.status_code == 200
    body = res.json()
    assert body["expires_in"] == 900
    assert body["user"] == {"id": str(demo_id("user", "owner")), "name": "김사장", "role": "owner"}

    claims = decode_token(body["access_token"], "access")
    assert claims.company_id == demo_id("company", COMPANY_CODE)
    assert decode_token(body["refresh_token"], "refresh").user_id == claims.user_id


def test_email_is_case_insensitive(client):
    res = client.post(URL, json={"email": " Manager@Hanseo.kr", "password": "demo-manager-1234"})
    assert res.status_code == 200
    assert res.json()["user"]["role"] == "manager"


@pytest.mark.parametrize(
    "body",
    [
        {"email": "owner@hanseo.kr", "password": "wrong"},
        {"email": "nobody@hanseo.kr", "password": "demo-owner-1234"},
    ],
    ids=["wrong-password", "unknown-email"],
)
def test_bad_credentials_are_401(client, body):
    res = client.post(URL, json=body)
    assert res.status_code == 401
    assert res.json()["code"] == "INVALID_CREDENTIALS"


def test_missing_field_is_400(client):
    res = client.post(URL, json={"email": "owner@hanseo.kr"})
    assert res.status_code == 400
