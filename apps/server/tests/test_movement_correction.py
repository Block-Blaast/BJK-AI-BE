import uuid

import pytest
from bjk_server.db.models import Movement
from bjk_server.seed.demo import demo_id
from sqlalchemy.orm import Session

from .conftest import auth_header

PART = demo_id("part", "6205")


@pytest.fixture
def out_movement(client, demo_db):
    """볼베어링 6205ZZ 재고 3에서 2개 출고한 원장 행."""
    demo_db.reseed()
    body = {"client_message_id": f"c-{uuid.uuid4()}", "type": "OUT", "part_id": str(PART), "qty": 2}
    res = client.post("/api/v1/chat/entries", json=body, headers=auth_header("worker"))
    assert res.json()["stock_after"] == 1
    return res.json()["movement"]["id"]


def _correct(client, movement_id, qty, reason="수량 오기, 실제 1개 출고", user="manager"):
    return client.post(
        f"/api/v1/movements/{movement_id}/correction",
        json={"reason": reason, "corrected_qty": qty},
        headers=auth_header(user),
    )


def test_correction_adds_adjust_and_keeps_original(client, demo_db, out_movement):
    res = _correct(client, out_movement, -1)
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["stock_after"] == 2
    assert {k: body["movement"][k] for k in ("type", "qty", "reason", "corrects")} == {
        "type": "ADJUST",
        "qty": 1,
        "reason": "수량 오기, 실제 1개 출고",
        "corrects": out_movement,
    }
    with Session(demo_db.admin) as s:
        original = s.get(Movement, out_movement)
        assert (original.type, original.qty) == ("OUT", -2)
        assert s.get(Movement, body["movement"]["id"]).author_id == demo_id("user", "manager")

    history = client.get(f"/api/v1/parts/{PART}/movements", headers=auth_header("worker")).json()[
        "items"
    ]
    assert history[0]["corrects"] == out_movement


def test_repeated_correction_adds_only_remaining_diff(client, out_movement):
    _correct(client, out_movement, -1)
    second = _correct(client, out_movement, 0, reason="출고 없었음")
    assert second.json()["movement"]["qty"] == 1
    assert second.json()["stock_after"] == 3
    same = _correct(client, out_movement, 0)
    assert same.status_code == 400
    assert same.json()["detail"] == {"current_qty": 0}


@pytest.mark.parametrize(
    ("qty", "reason"), [(1, "부호 오류"), (-1, " ")], ids=["sign-mismatch", "blank-reason"]
)
def test_invalid_correction_is_400(client, out_movement, qty, reason):
    assert _correct(client, out_movement, qty, reason=reason).status_code == 400


def test_correction_of_correction_is_rejected(client, out_movement):
    correction = _correct(client, out_movement, -1).json()["movement"]["id"]
    res = _correct(client, correction, 0)
    assert res.status_code == 400
    assert res.json()["detail"] == {"corrects": out_movement}


def test_worker_cannot_correct(client, out_movement):
    assert _correct(client, out_movement, -1, user="worker").status_code == 403


def test_unknown_movement_is_404(client, demo_db):
    assert _correct(client, uuid.uuid4(), -1).status_code == 404
