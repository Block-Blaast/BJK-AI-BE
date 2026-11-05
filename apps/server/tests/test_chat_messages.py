from datetime import UTC, datetime

import pytest
from bjk_server.db.models import ChatEntry, ChatMessage
from bjk_server.seed.demo import demo_id
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .conftest import auth_header

URL = "/api/v1/chat/messages"
NOW = datetime(2026, 11, 4, 1, 0, 0, tzinfo=UTC)


def test_without_ai_falls_back_to_form_card(client, demo_db):
    demo_db.reseed()
    res = client.post(
        URL,
        json={"client_message_id": "m-1", "text": "3호기 베어링 두 개 씀"},
        headers=auth_header("worker"),
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ai"] == {"used": True, "fallback": True, "reason": "error"}
    assert [c["type"] for c in body["cards"]] == ["form"]


def test_ai_timeout_falls_back_with_reason(chat):
    body = chat("타임아웃").json()
    assert body["ai"]["reason"] == "timeout"
    assert body["cards"][0]["type"] == "form"


def test_ambiguous_part_gives_select_card_equipment_part_first(chat):
    body = chat("3호기 베어링 두 개 씀").json()
    assert body["intent"] == "OUT"
    assert body["reply"] == "어떤 베어링인가요?"
    card = body["cards"][0]
    assert card["type"] == "select"
    assert card["qty"] == 2
    assert card["equipment"]["name"] == "3호기"
    assert [(c["name"], c["reason"]) for c in card["candidates"]] == [
        ("볼베어링 6205ZZ", "equipment_part"),
        ("볼베어링 6204ZZ", "name"),
    ]
    assert body["ai"] == {"used": True, "fallback": False, "reason": None}


def test_confirmed_alias_gives_confirm_card(chat):
    card = chat("베어링 작은 거 2개 씀").json()["cards"][0]
    assert card["type"] == "confirm"
    assert (card["part_id"], card["stock"], card["qty"]) == (str(demo_id("part", "6205")), 3, 2)


def test_qty_over_five_times_past_max_gives_warning_card(chat):
    # 시드에서 볼베어링 6205ZZ의 과거 1회 최대 출고는 1개
    assert chat("베어링 작은 거 5개 씀").json()["cards"][0]["type"] == "confirm"
    body = chat("베어링 작은 거 6개 씀").json()
    assert body["cards"][0]["type"] == "warning"
    assert body["reply"] == "볼베어링 6205ZZ 6개 맞나요? 평소보다 훨씬 많아요."


def test_in_with_single_match_is_confirm(chat):
    body = chat("V벨트 3개 들어옴").json()
    assert body["intent"] == "IN"
    assert body["cards"][0]["type"] == "confirm"
    assert body["reply"] == "V벨트 A-42 3개 입고할까요?"


def test_unknown_part_gives_unregistered_card(chat):
    assert chat("기어 하나 씀").json()["cards"][0]["type"] == "unregistered"


def test_query_replies_stock_without_card(chat):
    body = chat("6205 몇 개 있어?").json()
    assert body["cards"] == []
    assert "볼베어링 6205ZZ 현재 재고 3개" in body["reply"]


def test_other_intent_replies_help(chat):
    body = chat("안녕").json()
    assert body["cards"] == []
    assert body["reply"] == "기록, 조회, 발주 요청을 도와드려요."


def test_card_expires_in_ten_minutes(chat, demo_db):
    card = chat("베어링 작은 거 2개 씀").json()["cards"][0]
    with Session(demo_db.admin) as s:
        entry = s.get(ChatEntry, card["entry_id"])
        assert (entry.expires_at - entry.created_at).total_seconds() == pytest.approx(600, abs=5)
        assert entry.user_id == demo_id("user", "worker")


def test_same_client_message_id_returns_first_result(chat, demo_db):
    first = chat("베어링 작은 거 2개 씀", client_message_id="dup-1").json()
    again = chat("베어링 작은 거 2개 씀", client_message_id="dup-1").json()
    assert again == first
    with Session(demo_db.admin) as s:
        count = s.scalar(
            select(func.count())
            .select_from(ChatMessage)
            .where(ChatMessage.client_message_id == "dup-1")
        )
    assert count == 1


@pytest.mark.parametrize("other_user", [False, True], ids=["different-body", "different-user"])
def test_reused_message_id_rejects_changed_request_or_user(chat, demo_db, other_user):
    first = chat("베어링 작은 거 2개 씀", client_message_id="message-conflict")
    assert first.status_code == 200
    response = chat(
        "베어링 작은 거 2개 씀" if other_user else "베어링 작은 거 3개 씀",
        user="worker2" if other_user else "worker",
        client_message_id="message-conflict",
    )
    assert response.status_code == 409
    assert response.json()["code"] == "IDEMPOTENCY_CONFLICT"
    with Session(demo_db.admin) as session:
        count = session.scalar(select(func.count()).select_from(ChatMessage).where(
            ChatMessage.client_message_id == "message-conflict"
        ))
    assert count == 1


def test_text_over_500_chars_is_400(chat):
    res = chat("가" * 501)
    assert res.status_code == 400
    assert res.json()["code"] == "VALIDATION_ERROR"


def test_rate_limited_after_20_per_minute(chat):
    for _ in range(20):
        assert chat("안녕").status_code == 200
    res = chat("안녕")
    assert res.status_code == 429
    assert chat("안녕", user="worker2").status_code == 200


def test_requires_login(client):
    assert client.post(URL, json={"client_message_id": "x", "text": "안녕"}).status_code == 401
