import uuid

import pytest
from bjk_server.db.models import Movement, Part
from bjk_server.seed.demo import PARTS, demo_id
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .conftest import auth_header

URL = "/api/v1/parts"


@pytest.fixture
def fresh(demo_db):
    demo_db.reseed()


def _post(client, body, user="manager"):
    return client.post(URL, json=body, headers=auth_header(user))


def test_create_part_with_initial_stock_as_adjust(client, demo_db, fresh):
    res = _post(
        client,
        {
            "name": " 볼베어링 6206ZZ ",
            "unit": "개",
            "category_id": str(demo_id("category", "bearing")),
            "default_supplier_id": str(demo_id("supplier", "a")),
            "spec": {"bearing_no": "6206", "shield": "ZZ"},
            "monthly_estimate": 2,
            "initial_stock": 5,
        },
    )
    assert res.status_code == 201, res.text
    part = res.json()
    assert (part["name"], part["stock"], part["spec"]["bearing_no"]) == (
        "볼베어링 6206ZZ",
        5,
        "6206",
    )
    with Session(demo_db.admin) as s:
        movement = s.scalar(select(Movement).where(Movement.part_id == part["id"]))
        assert (movement.type, movement.qty, movement.reason) == ("ADJUST", 5, "초기 재고")
        assert movement.author_id == demo_id("user", "manager")
    names = [i["name"] for i in client.get(URL, headers=auth_header("worker")).json()["items"]]
    assert "볼베어링 6206ZZ" in names
    assert len(names) == len(PARTS) + 1


def test_create_without_stock_records_nothing(client, demo_db, fresh):
    part = _post(client, {"name": "평와셔 M8", "unit": "개"}).json()
    assert part["stock"] == 0
    with Session(demo_db.admin) as s:
        assert s.scalar(select(Movement).where(Movement.part_id == part["id"])) is None


def test_update_part_fields_without_touching_stock(client, fresh):
    p20 = demo_id("part", "p20")
    res = client.patch(
        f"{URL}/{p20}",
        json={"location": "C선반 4칸", "import_override": "high", "monthly_estimate": None},
        headers=auth_header("manager"),
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert (body["location"], body["import_override"], body["stock"]) == ("C선반 4칸", "high", 1040)


@pytest.mark.parametrize(
    "body",
    [
        {"name": "x"},
        {"name": " ", "unit": "개"},
        {"name": "x", "unit": "개", "initial_stock": -1},
        {"name": "x", "unit": "개", "import_override": "none"},
        {"name": "x", "unit": "개", "spec": {"a": [1]}},
    ],
)
def test_invalid_create_is_400(client, fresh, body):
    assert _post(client, body).status_code == 400


def test_unknown_references_are_404(client, fresh):
    res = _post(client, {"name": "x", "unit": "개", "category_id": str(uuid.uuid4())})
    assert res.status_code == 404
    assert "category_id" in res.json()["detail"]
    res = client.patch(
        f"{URL}/{uuid.uuid4()}", json={"location": "x"}, headers=auth_header("manager")
    )
    assert res.status_code == 404


def test_merged_part_cannot_be_updated(client, demo_db, fresh):
    with Session(demo_db.admin) as s, s.begin():
        s.execute(
            update(Part)
            .where(Part.id == demo_id("part", "m820"))
            .values(merged_into=demo_id("part", "p20"))
        )
    res = client.patch(
        f"{URL}/{demo_id('part', 'm820')}", json={"location": "x"}, headers=auth_header("manager")
    )
    assert res.status_code == 404
    assert res.json()["detail"] == {"merged_into": str(demo_id("part", "p20"))}


def test_worker_cannot_write_parts(client, fresh):
    assert _post(client, {"name": "x", "unit": "개"}, user="worker").status_code == 403
