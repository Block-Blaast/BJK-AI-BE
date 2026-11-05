import uuid

import pytest
from bjk_server.seed.demo import demo_id

from .conftest import auth_header

URL = "/api/v1/suppliers"
A = demo_id("supplier", "a")
P6205 = demo_id("part", "6205")


@pytest.fixture
def fresh(demo_db):
    demo_db.reseed()


def _call(client, method, path="", user="manager", **kwargs):
    return client.request(method, f"{URL}{path}", headers=auth_header(user), **kwargs)


def test_lists_suppliers_with_part_counts(client, fresh):
    items = _call(client, "GET").json()["items"]
    assert [(s["name"], s["default_lead_time_days"], s["part_count"]) for s in items] == [
        ("공급사 A", 7, 5),
        ("공급사 B", 5, 3),
    ]


def test_detail_has_part_terms(client, fresh):
    body = _call(client, "GET", f"/{A}").json()
    bearing = next(p for p in body["parts"] if p["part_id"] == str(P6205))
    assert bearing == {
        "part_id": str(P6205),
        "name": "볼베어링 6205ZZ",
        "unit_price": 18000,
        "moq": 10,
        "price_tiers": [{"min_qty": 20, "unit_price": 16500}],
        "shipping_fee": 4000,
    }


def test_create_update_supplier(client, fresh):
    res = _call(
        client,
        "POST",
        json={"name": "공급사 C", "default_lead_time_days": 10, "holidays": ["2026-12-25"]},
    )
    assert res.status_code == 201, res.text
    created = res.json()
    assert (created["part_count"], created["holidays"], created["contact"]) == (
        0,
        ["2026-12-25"],
        None,
    )
    patched = _call(
        client,
        "PATCH",
        f"/{created['id']}",
        json={"contact": "02-000-0000", "default_lead_time_days": None},
    ).json()
    assert (patched["contact"], patched["default_lead_time_days"], patched["name"]) == (
        "02-000-0000",
        None,
        "공급사 C",
    )


def test_put_and_delete_part_terms(client, fresh):
    oil = demo_id("part", "oil")
    b = demo_id("supplier", "b")
    body = {"unit_price": 45000, "moq": 2, "price_tiers": [{"min_qty": 10, "unit_price": 43000}]}
    res = _call(client, "PUT", f"/{b}/parts/{oil}", json=body)
    assert res.status_code == 200, res.text
    assert res.json()["shipping_fee"] == 0
    res = _call(client, "PUT", f"/{b}/parts/{oil}", json={"unit_price": 44000})
    assert (res.json()["unit_price"], res.json()["price_tiers"]) == (44000, [])
    assert _call(client, "GET", f"/{b}").json()["part_count"] == 4
    assert _call(client, "DELETE", f"/{b}/parts/{oil}").status_code == 204
    assert _call(client, "DELETE", f"/{b}/parts/{oil}").status_code == 404


@pytest.mark.parametrize(
    "tiers",
    [
        [{"min_qty": 20, "unit_price": 1}, {"min_qty": 10, "unit_price": 1}],
        [{"min_qty": 10, "unit_price": 1}, {"min_qty": 10, "unit_price": 2}],
        [{"min_qty": 0, "unit_price": 1}],
    ],
    ids=["descending", "duplicate", "zero"],
)
def test_invalid_price_tiers_are_400(client, fresh, tiers):
    res = _call(client, "PUT", f"/{A}/parts/{P6205}", json={"unit_price": 1, "price_tiers": tiers})
    assert res.status_code == 400


def test_duplicate_name_and_unknown_ids(client, fresh):
    assert _call(client, "POST", json={"name": "공급사 A"}).json()["code"] == "NAME_TAKEN"
    assert _call(client, "GET", f"/{uuid.uuid4()}").status_code == 404
    res = _call(client, "PUT", f"/{A}/parts/{uuid.uuid4()}", json={"unit_price": 1})
    assert res.status_code == 404


def test_worker_cannot_manage_suppliers(client, fresh):
    assert _call(client, "GET", user="worker").status_code == 403
