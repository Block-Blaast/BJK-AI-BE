import uuid

import pytest
from bjk_server.db.models import Company, User
from bjk_server.security import create_refresh_token
from bjk_server.seed.demo import COMPANY_CODE, USERS, demo_id
from sqlalchemy.orm import Session

from .conftest import auth_header

URL = "/api/v1/users"


@pytest.fixture
def fresh(demo_db):
    demo_db.reseed()
    yield demo_db
    demo_db.reseed()


def test_lists_company_users_by_name(client, fresh):
    res = client.get(URL, headers=auth_header("owner"))
    assert res.status_code == 200
    items = res.json()["items"]
    assert [i["name"] for i in items] == sorted(u.name for u in USERS)
    worker = next(i for i in items if i["name"] == "이현장")
    assert worker == {
        "id": str(demo_id("user", "worker")),
        "name": "이현장",
        "role": "worker",
        "email": None,
        "has_pin": True,
        "active": True,
    }
    owner = next(i for i in items if i["role"] == "owner")
    assert owner["has_pin"] is False


def test_promote_worker_applies_on_token_refresh(client, fresh):
    worker_id = demo_id("user", "worker")
    res = client.patch(f"{URL}/{worker_id}", json={"role": "manager"}, headers=auth_header("owner"))
    assert res.status_code == 200
    assert res.json()["role"] == "manager"

    refresh = create_refresh_token(worker_id, demo_id("company", COMPANY_CODE), "worker")
    tokens = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh}).json()
    me = client.get("/api/v1/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert me.json()["role"] == "manager"


def test_demote_manager(client, fresh):
    res = client.patch(
        f"{URL}/{demo_id('user', 'manager')}", json={"role": "worker"}, headers=auth_header("owner")
    )
    assert res.status_code == 200
    assert res.json()["role"] == "worker"


@pytest.mark.parametrize(
    ("target", "role", "reason"),
    [("owner", "manager", "self"), ("worker", "owner", None)],
)
def test_rejects_self_and_owner_role(client, fresh, target, role, reason):
    res = client.patch(
        f"{URL}/{demo_id('user', target)}", json={"role": role}, headers=auth_header("owner")
    )
    assert res.status_code == 400
    assert res.json()["code"] == "VALIDATION_ERROR"
    if reason:
        assert res.json()["detail"]["reason"] == reason


def test_rejects_changing_another_owner(client, fresh):
    second_owner = uuid.uuid4()
    with Session(fresh.admin) as s, s.begin():
        s.add(
            User(
                id=second_owner,
                company_id=demo_id("company", COMPANY_CODE),
                name="공동대표",
                role="owner",
            )
        )
    res = client.patch(
        f"{URL}/{second_owner}", json={"role": "worker"}, headers=auth_header("owner")
    )
    assert res.status_code == 400
    assert res.json()["detail"]["reason"] == "owner"


def test_other_company_user_is_404(client, fresh):
    other_company, other_user = uuid.uuid4(), uuid.uuid4()
    with Session(fresh.admin) as s, s.begin():
        s.add(Company(id=other_company, name="다른회사", code="OTHER2"))
        s.flush()
        s.add(User(id=other_user, company_id=other_company, name="남", role="worker"))
    res = client.patch(
        f"{URL}/{other_user}", json={"role": "manager"}, headers=auth_header("owner")
    )
    assert res.status_code == 404
    names = [i["name"] for i in client.get(URL, headers=auth_header("owner")).json()["items"]]
    assert "남" not in names


@pytest.mark.parametrize("user", ["manager", "worker"])
def test_only_owner(client, user):
    assert client.get(URL, headers=auth_header(user)).status_code == 403
    res = client.patch(
        f"{URL}/{demo_id('user', 'worker2')}", json={"role": "manager"}, headers=auth_header(user)
    )
    assert res.status_code == 403
