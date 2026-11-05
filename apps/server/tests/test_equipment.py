import uuid

import pytest
from bjk_server.seed.demo import demo_id

from .conftest import auth_header

URL = "/api/v1/equipment"
EQ3 = demo_id("equipment", "eq3")


@pytest.fixture
def fresh(demo_db):
    demo_db.reseed()


def _call(client, method, path="", user="manager", **kwargs):
    return client.request(method, f"{URL}{path}", headers=auth_header(user), **kwargs)


def test_lists_equipment_with_linked_parts(client, fresh):
    items = _call(client, "GET").json()["items"]
    assert [e["name"] for e in items] == ["1호기", "2호기", "3호기"]
    eq3 = items[2]
    assert (eq3["loss_per_hour"], eq3["operating_hours"], eq3["loss_is_estimate"]) == (
        50000,
        16,
        True,
    )
    assert [(p["name"], p["qty_per_maintenance"]) for p in eq3["parts"]] == [
        ("볼베어링 6205ZZ", 4),
        ("오링 P-20", 100),
    ]


def test_create_without_loss_and_replace_parts(client, fresh):
    res = _call(
        client,
        "POST",
        json={
            "name": "4호기",
            "parts": [{"part_id": str(demo_id("part", "a42")), "qty_per_maintenance": 1}],
        },
    )
    assert res.status_code == 201, res.text
    created = res.json()
    assert (created["loss_per_hour"], created["operating_hours"]) == (0, 8)
    oil = str(demo_id("part", "oil"))
    patched = _call(
        client,
        "PATCH",
        f"/{created['id']}",
        json={"operating_hours": 12, "parts": [{"part_id": oil, "qty_per_maintenance": 2}]},
    ).json()
    assert patched["operating_hours"] == 12
    assert [p["part_id"] for p in patched["parts"]] == [oil]
    # parts를 보내지 않으면 연결은 그대로
    kept = _call(client, "PATCH", f"/{created['id']}", json={"loss_per_hour": 10000}).json()
    assert [p["part_id"] for p in kept["parts"]] == [oil]


def test_duplicate_name_ignores_case(client, fresh):
    _call(client, "POST", json={"name": "CNC-1"})
    res = _call(client, "POST", json={"name": "cnc-1"})
    assert (res.status_code, res.json()["code"]) == (409, "NAME_TAKEN")


@pytest.mark.parametrize(
    "body",
    [
        {"name": "x", "operating_hours": 25},
        {"name": "x", "loss_per_hour": -1},
        {
            "name": "x",
            "parts": [
                {"part_id": str(demo_id("part", "a42")), "qty_per_maintenance": 1},
                {"part_id": str(demo_id("part", "a42")), "qty_per_maintenance": 2},
            ],
        },
        {
            "name": "x",
            "parts": [{"part_id": str(demo_id("part", "a42")), "qty_per_maintenance": 0}],
        },
    ],
    ids=["hours", "loss", "duplicate-part", "zero-qty"],
)
def test_invalid_equipment_is_400(client, fresh, body):
    assert _call(client, "POST", json=body).status_code == 400


def test_unknown_part_or_equipment_is_404(client, fresh):
    body = {"name": "x", "parts": [{"part_id": str(uuid.uuid4()), "qty_per_maintenance": 1}]}
    assert _call(client, "POST", json=body).status_code == 404
    assert _call(client, "GET", f"/{uuid.uuid4()}").status_code == 404
    assert _call(client, "PATCH", f"/{EQ3}", json={"name": None}).status_code == 400


def test_worker_cannot_manage_equipment(client, fresh):
    assert _call(client, "GET", user="worker").status_code == 403
