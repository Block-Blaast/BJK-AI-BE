from bjk_server.chat.interpreter import Interpretation
from bjk_server.db.models import ChatEntry, Maintenance
from bjk_server.seed.demo import demo_id
from sqlalchemy.orm import Session

from .chat_fakes import PARSED
from .conftest import auth_header

EQ3_NEXT = demo_id("maintenance", "eq3:16")

PARSED.update(
    {
        "3호기 정비 끝": Interpretation("MAINTENANCE_DONE", equipment_text="3호기"),
        "1호기 정비 끝": Interpretation("MAINTENANCE_DONE", equipment_text="1호기"),
        "정비 끝": Interpretation("MAINTENANCE_DONE"),
    }
)


def _confirm(client, entry_id, user="worker"):
    return client.post(
        f"/api/v1/chat/entries/{entry_id}/confirm", json={}, headers=auth_header(user)
    )


def test_maintenance_done_shows_nearest_open_maintenance_card(chat, demo_db):
    body = chat("3호기 정비 끝").json()
    assert body["intent"] == "MAINTENANCE_DONE"
    [card] = body["cards"]
    assert card["type"] == "confirm"
    assert card["equipment"]["name"] == "3호기"
    assert card["maintenance"]["id"] == str(EQ3_NEXT)
    assert body["reply"].startswith("3호기 ") and body["reply"].endswith("예정 정비를 완료할까요?")
    with Session(demo_db.admin) as s:
        assert s.get(Maintenance, EQ3_NEXT).completed_at is None


def test_confirm_completes_maintenance_like_set09(chat, client, demo_db):
    card = chat("3호기 정비 끝").json()["cards"][0]
    res = _confirm(client, card["entry_id"])
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["intent"] == "MAINTENANCE_DONE"
    assert body["maintenance_id"] == str(EQ3_NEXT)
    assert body["reply"] == "정비 완료로 기록했어요."
    with Session(demo_db.admin) as s:
        m = s.get(Maintenance, EQ3_NEXT)
        assert m.completed_by == demo_id("user", "worker")
        assert m.completed_at is not None
        assert s.get(ChatEntry, card["entry_id"]).status == "confirmed"
    assert _confirm(client, card["entry_id"]).status_code == 409


def test_confirm_already_completed_maintenance_conflicts(chat, client):
    card = chat("3호기 정비 끝").json()["cards"][0]
    done = client.post(
        f"/api/v1/maintenance/{EQ3_NEXT}/complete", json={}, headers=auth_header("manager")
    )
    assert done.status_code == 200, done.text
    res = _confirm(client, card["entry_id"])
    assert res.status_code == 409
    assert res.json()["detail"]["status"] == "completed"


def test_maintenance_done_without_equipment_or_schedule_has_no_card(chat):
    body = chat("정비 끝").json()
    assert (body["reply"], body["cards"]) == ("어느 설비의 정비인지 알려 주세요.", [])
    body = chat("1호기 정비 끝").json()
    assert (body["reply"], body["cards"]) == ("1호기에 완료할 정비 일정이 없어요.", [])
