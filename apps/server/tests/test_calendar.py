import uuid

import pytest
from bjk_server.seed.demo import demo_id

from .conftest import auth_header

URL = "/api/v1/calendar"


@pytest.fixture
def fresh(demo_db):
    demo_db.reseed()


def _call(client, method, path="", user="manager", **kwargs):
    return client.request(method, f"{URL}{path}", headers=auth_header(user), **kwargs)


def test_lists_seed_holidays(client, fresh):
    items = _call(client, "GET").json()["items"]
    assert [(e["name"], e["start"], e["end"], e["scope"]) for e in items] == [
        ("춘절", "2027-02-05", "2027-02-13", "CN"),
        ("설날 연휴", "2027-02-06", "2027-02-09", "KR"),
    ]


def test_filters_by_overlap_and_scope(client, fresh):
    def names(**params):
        return [e["name"] for e in _call(client, "GET", params=params).json()["items"]]

    assert names(**{"from": "2027-02-10"}) == ["춘절"]
    assert names(**{"to": "2027-02-05"}) == ["춘절"]
    assert names(scope="KR") == ["설날 연휴"]
    assert names(**{"to": "2026-12-31"}) == []


def test_create_update_delete_supplier_holiday(client, fresh):
    supplier = str(demo_id("supplier", "a"))
    res = _call(
        client,
        "POST",
        json={
            "name": "공급사 A 재고 조사",
            "start": "2026-12-28",
            "end": "2026-12-31",
            "scope": "supplier",
            "supplier_id": supplier,
        },
    )
    assert res.status_code == 201, res.text
    event = res.json()
    patched = _call(client, "PATCH", f"/{event['id']}", json={"end": "2026-12-30"}).json()
    assert (patched["end"], patched["supplier_id"]) == ("2026-12-30", supplier)
    assert _call(client, "DELETE", f"/{event['id']}").status_code == 204
    assert _call(client, "DELETE", f"/{event['id']}").status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {"name": "x", "start": "2027-01-02", "end": "2027-01-01", "scope": "KR"},
        {"name": "x", "start": "2027-01-01", "end": "2027-01-01", "scope": "supplier"},
        {
            "name": "x",
            "start": "2027-01-01",
            "end": "2027-01-01",
            "scope": "KR",
            "supplier_id": str(demo_id("supplier", "a")),
        },
        {"name": "x", "start": "2027-01-01", "end": "2027-01-01", "scope": "JP"},
    ],
    ids=["end-before-start", "supplier-missing", "supplier-on-kr", "unknown-scope"],
)
def test_invalid_event_is_400(client, fresh, body):
    assert _call(client, "POST", json=body).status_code == 400


def test_patch_rechecks_dates(client, fresh):
    event = _call(client, "GET").json()["items"][0]
    assert _call(client, "PATCH", f"/{event['id']}", json={"end": "2027-01-01"}).status_code == 400


def test_unknown_supplier_404_and_worker_403(client, fresh):
    body = {
        "name": "x",
        "start": "2027-01-01",
        "end": "2027-01-01",
        "scope": "supplier",
        "supplier_id": str(uuid.uuid4()),
    }
    assert _call(client, "POST", json=body).status_code == 404
    assert _call(client, "GET", user="worker").status_code == 403
