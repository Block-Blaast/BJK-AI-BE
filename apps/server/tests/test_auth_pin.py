from datetime import UTC, datetime, timedelta

import pytest
from bjk_server import pin_lock, ratelimit
from bjk_server.errors import ApiError
from bjk_server.security import decode_token
from bjk_server.seed.demo import COMPANY_CODE, demo_id

MEMBERS = f"/api/v1/auth/companies/{COMPANY_CODE}/members"
PIN_LOGIN = "/api/v1/auth/pin-login"
WORKER = demo_id("user", "worker")
NOW = datetime(2026, 11, 4, 1, 0, 30, tzinfo=UTC)


@pytest.fixture(autouse=True)
def fresh(demo_db, monkeypatch):
    demo_db.reseed()
    monkeypatch.setattr(ratelimit, "utcnow", lambda: NOW)
    monkeypatch.setattr(pin_lock, "utcnow", lambda: NOW)


def _login(client, pin, user=WORKER, code=COMPANY_CODE):
    return client.post(PIN_LOGIN, json={"company_code": code, "user_id": str(user), "pin": pin})


def test_members_lists_pin_users_by_name_only(client):
    res = client.get(MEMBERS)
    assert res.status_code == 200
    items = res.json()["items"]
    assert [i["name"] for i in items] == ["박정비", "이현장", "최관리"]
    assert all(set(i) == {"user_id", "name"} for i in items)


def test_members_code_is_case_insensitive(client):
    assert client.get(f"/api/v1/auth/companies/{COMPANY_CODE.lower()}/members").status_code == 200


def test_members_unknown_code_is_404(client):
    res = client.get("/api/v1/auth/companies/NOPE00/members")
    assert res.status_code == 404
    assert res.json()["code"] == "NOT_FOUND"


def test_members_rate_limited_per_ip(client):
    for _ in range(10):
        assert client.get(MEMBERS).status_code == 200
    res = client.get(MEMBERS)
    assert res.status_code == 429
    assert res.json()["code"] == "RATE_LIMITED"
    assert res.headers["Retry-After"] == "30"


def test_failed_lookups_also_count_toward_limit(client):
    for _ in range(10):
        client.get("/api/v1/auth/companies/NOPE00/members")
    assert client.get(MEMBERS).status_code == 429


def test_pin_login_issues_tokens(client):
    res = _login(client, "1234")
    assert res.status_code == 200
    body = res.json()
    assert body["user"]["name"] == "이현장"
    assert decode_token(body["access_token"], "access").role == "worker"


def test_wrong_pin_reports_remaining_attempts(client):
    res = _login(client, "0000")
    assert res.status_code == 401
    assert res.json()["code"] == "INVALID_PIN"
    assert res.json()["detail"] == {"remaining_attempts": 4}


def test_five_failures_lock_for_ten_minutes(client, monkeypatch):
    for remaining in (4, 3, 2, 1):
        assert _login(client, "0000").json()["detail"]["remaining_attempts"] == remaining
    res = _login(client, "0000")
    assert res.status_code == 423
    assert res.json()["code"] == "PIN_LOCKED"
    assert res.json()["detail"]["retry_after_seconds"] == 600

    assert _login(client, "1234").status_code == 423

    monkeypatch.setattr(pin_lock, "utcnow", lambda: NOW + timedelta(minutes=10, seconds=1))
    assert _login(client, "1234").status_code == 200


def test_success_resets_consecutive_failures(client):
    for _ in range(4):
        _login(client, "0000")
    assert _login(client, "1234").status_code == 200
    assert _login(client, "0000").json()["detail"]["remaining_attempts"] == 4


def test_lock_is_per_account(client):
    for _ in range(5):
        _login(client, "0000")
    assert _login(client, "5678", user=demo_id("user", "worker2")).status_code == 200


@pytest.mark.parametrize(
    ("user", "code"),
    [
        (demo_id("user", "nobody"), COMPANY_CODE),
        (WORKER, "NOPE00"),
        (demo_id("user", "owner"), COMPANY_CODE),
    ],
    ids=["unknown-user", "unknown-company", "user-without-pin"],
)
def test_unknown_target_is_404(client, user, code):
    assert _login(client, "1234", user=user, code=code).status_code == 404


def test_rate_limit_window_resets(demo_db):
    for _ in range(2):
        ratelimit.hit(demo_db.app, "unit", 2, 60, now=NOW)
    with pytest.raises(ApiError) as exc:
        ratelimit.hit(demo_db.app, "unit", 2, 60, now=NOW)
    assert exc.value.headers == {"Retry-After": "30"}
    ratelimit.hit(demo_db.app, "unit", 2, 60, now=NOW + timedelta(seconds=30))
