import pytest
from bjk_server.db.models import CompanySettings
from bjk_server.defaults import DEFAULT_SETTINGS
from bjk_server.seed.demo import COMPANY_CODE, demo_id
from sqlalchemy.orm import Session

from .conftest import auth_header

URL = "/api/v1/settings"


@pytest.fixture
def fresh(demo_db):
    demo_db.reseed()
    yield demo_db
    demo_db.reseed()


def test_get_returns_seeded_defaults(client, fresh):
    res = client.get(URL, headers=auth_header("owner"))
    assert res.status_code == 200
    body = res.json()
    assert {k: body[k] for k in ("notify", "review", "system")} == DEFAULT_SETTINGS
    assert body["updated_at"] is not None


def test_get_without_row_returns_defaults(client, fresh):
    with Session(fresh.admin) as s, s.begin():
        s.delete(s.get(CompanySettings, demo_id("company", COMPANY_CODE)))
    body = client.get(URL, headers=auth_header("owner")).json()
    assert body["review"] == DEFAULT_SETTINGS["review"]
    assert body["updated_at"] is None


def test_patch_changes_only_sent_keys(client, fresh):
    before = client.get(URL, headers=auth_header("owner")).json()
    res = client.patch(
        URL,
        json={"notify": {"briefing_time": "07:00"}, "review": {"c08_days": 7}},
        headers=auth_header("owner"),
    )
    assert res.status_code == 200
    body = res.json()
    assert body["notify"]["briefing_time"] == "07:00"
    assert body["notify"]["quiet_hours"] == DEFAULT_SETTINGS["notify"]["quiet_hours"]
    assert body["review"]["c08_days"] == 7
    assert body["review"]["service_level"] == DEFAULT_SETTINGS["review"]["service_level"]
    assert body["system"] == DEFAULT_SETTINGS["system"]
    assert body["updated_at"] >= before["updated_at"]
    assert client.get(URL, headers=auth_header("owner")).json() == body


def test_patch_nested_service_level_keeps_other_classes(client, fresh):
    body = client.patch(
        URL, json={"review": {"service_level": {"A": 0.99}}}, headers=auth_header("owner")
    ).json()
    assert body["review"]["service_level"] == {"A": 0.99, "B": 0.95, "C": 0.90}


def test_patch_creates_row_when_missing(client, fresh):
    with Session(fresh.admin) as s, s.begin():
        s.delete(s.get(CompanySettings, demo_id("company", COMPANY_CODE)))
    res = client.patch(URL, json={"review": {"c08_days": 3}}, headers=auth_header("owner"))
    assert res.status_code == 200
    assert res.json()["review"]["c08_days"] == 3
    assert res.json()["review"]["next_order_weeks"] == 4


@pytest.mark.parametrize(
    "body",
    [
        {"system": {"external_k": 0.5}},
        {"notify": {"briefing_time": "05:59"}},
        {"notify": {"briefing_time": "10:01"}},
        {"notify": {"quiet_hours": {"start": "25:00"}}},
        {"review": {"service_level": {"A": 0.999}}},
        {"review": {"next_order_weeks": 9}},
        {"review": {"c02_months": 2}},
        {"review": {"c05_sigma": 0.5}},
        {"review": {"c06_ratio": 0.96}},
        {"review": {"c08_days": 0}},
        {"review": {"c08_days": None}},
        {"review": {"unknown": 1}},
    ],
)
def test_patch_rejects_system_and_out_of_range(client, fresh, body):
    res = client.patch(URL, json=body, headers=auth_header("owner"))
    assert res.status_code == 400
    assert res.json()["code"] == "VALIDATION_ERROR"
    assert (
        client.get(URL, headers=auth_header("owner")).json()["review"]
        == (DEFAULT_SETTINGS["review"])
    )


@pytest.mark.parametrize("user", ["manager", "worker"])
def test_only_owner(client, user):
    assert client.get(URL, headers=auth_header(user)).status_code == 403
    res = client.patch(URL, json={"review": {"c08_days": 7}}, headers=auth_header(user))
    assert res.status_code == 403
    assert res.json()["code"] == "FORBIDDEN_ROLE"


def test_requires_token(client):
    assert client.get(URL).status_code == 401
