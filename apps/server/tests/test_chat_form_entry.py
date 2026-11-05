import pytest
from bjk_server.db.models import ChatEntry, Movement
from bjk_server.seed.demo import demo_id
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .conftest import auth_header

URL = "/api/v1/chat/entries"
P6205 = demo_id("part", "6205")


@pytest.fixture(autouse=True)
def fresh(demo_db):
    demo_db.reseed()


def _post(client, **body):
    payload = {"client_message_id": "f-1", "type": "OUT", "part_id": str(P6205), "qty": 2} | body
    return client.post(URL, json=payload, headers=auth_header("worker"))


def _movements(demo_db):
    with Session(demo_db.admin) as s:
        return s.scalar(select(func.count()).select_from(Movement).where(Movement.part_id == P6205))


def test_form_out_records_movement_like_confirm(client, demo_db):
    before = _movements(demo_db)
    res = _post(client, equipment_id=str(demo_id("equipment", "eq3")))
    assert res.status_code == 200
    body = res.json()
    assert body["intent"] == "OUT"
    assert body["movement"]["qty"] == -2
    assert body["stock_after"] == 1
    assert body["reply"] == "출고 완료. 남은 재고 1개"
    assert body["alias_learned"] is None
    assert _movements(demo_db) == before + 1

    with Session(demo_db.admin) as s:
        entry = s.scalar(select(ChatEntry).where(ChatEntry.type == "form"))
        assert (entry.status, entry.intent) == ("confirmed", "OUT")


def test_form_in(client):
    body = _post(client, type="IN", qty=10).json()
    assert (body["movement"]["qty"], body["stock_after"]) == (10, 13)


def test_same_client_message_id_records_once(client, demo_db):
    before = _movements(demo_db)
    first = _post(client, client_message_id="f-dup").json()
    again = _post(client, client_message_id="f-dup").json()
    assert again == first
    assert _movements(demo_db) == before + 1


@pytest.mark.parametrize(
    ("body", "status"),
    [
        ({"qty": 0}, 400),
        ({"type": "ADJUST"}, 400),
        ({"part_id": str(demo_id("part", "none"))}, 422),
        ({"equipment_id": str(demo_id("equipment", "none"))}, 404),
    ],
    ids=["zero-qty", "bad-type", "unknown-part", "unknown-equipment"],
)
def test_invalid_form_is_rejected_without_movement(client, demo_db, body, status):
    before = _movements(demo_db)
    assert _post(client, **body).status_code == status
    assert _movements(demo_db) == before


def test_requires_login(client):
    assert client.post(URL, json={}).status_code == 401


def test_form_movement_has_no_message(client, demo_db):
    body = _post(client, client_message_id="f-nomsg").json()
    with Session(demo_db.admin) as s:
        assert s.get(Movement, body["movement"]["id"]).message_id is None
