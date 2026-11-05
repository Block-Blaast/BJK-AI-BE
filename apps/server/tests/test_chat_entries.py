from datetime import timedelta

import pytest
from bjk_server import clock
from bjk_server.db.models import Movement, PartAlias
from bjk_server.seed.demo import demo_id
from sqlalchemy import select
from sqlalchemy.orm import Session

from .conftest import auth_header

P6205, P6204 = demo_id("part", "6205"), demo_id("part", "6204")


def _confirm(client, card, user="worker", **body):
    return client.post(
        f"/api/v1/chat/entries/{card['entry_id']}/confirm", json=body, headers=auth_header(user)
    )


def _cancel(client, card, user="worker"):
    return client.post(f"/api/v1/chat/entries/{card['entry_id']}/cancel", headers=auth_header(user))


def _card(chat, text):
    return chat(text).json()["cards"][0]


def test_select_then_confirm_records_out_and_learns_alias(client, chat, demo_db):
    card = _card(chat, "3호기 베어링 두 개 씀")
    res = _confirm(client, card, part_id=str(P6205))
    assert res.status_code == 200
    body = res.json()
    assert body["intent"] == "OUT"
    assert body["movement"]["qty"] == -2
    assert body["movement"]["part_id"] == str(P6205)
    assert body["movement"]["equipment_id"] == str(demo_id("equipment", "eq3"))
    assert body["stock_after"] == 1
    assert body["reply"] == "출고 완료. 남은 재고 1개"
    assert body["alias_learned"] == {"text": "베어링", "part_id": str(P6205)}
    assert body["triggered"] == {"draft_review_id": None, "audit_flag_id": None}

    with Session(demo_db.admin) as s:
        movement = s.get(Movement, body["movement"]["id"])
        assert movement.source_text == "3호기 베어링 두 개 씀"
        assert movement.author_id == demo_id("user", "worker")


def test_confirm_card_uses_card_values(client, chat):
    body = _confirm(client, _card(chat, "V벨트 3개 들어옴")).json()
    assert (body["intent"], body["movement"]["qty"], body["stock_after"]) == ("IN", 3, 5)
    assert body["reply"] == "입고 완료. 현재 재고 5개"
    assert body["alias_learned"] == {"text": "V벨트", "part_id": str(demo_id("part", "a42"))}


def test_confirm_can_override_qty(client, chat):
    body = _confirm(client, _card(chat, "베어링 작은 거 2개 씀"), qty=1).json()
    assert body["stock_after"] == 2


def _aliases(demo_db, text):
    with Session(demo_db.admin) as s:
        rows = s.scalars(select(PartAlias).where(PartAlias.text == text)).all()
        return {a.part_id: (a.confirmed_count, a.ambiguous) for a in rows}


def test_one_confirmation_to_other_part_is_not_ambiguous(client, chat, demo_db):
    _confirm(client, _card(chat, "3호기 베어링 두 개 씀"), part_id=str(P6205))
    _confirm(client, _card(chat, "3호기 베어링 두 개 씀"), part_id=str(P6204))
    assert _aliases(demo_db, "베어링") == {P6205: (1, False), P6204: (1, False)}


def test_second_confirmation_to_other_part_makes_alias_ambiguous(client, chat, demo_db):
    for part in (P6205, P6205, P6204, P6204):
        _confirm(client, _card(chat, "3호기 베어링 두 개 씀"), part_id=str(part))
    assert _aliases(demo_db, "베어링") == {P6205: (2, True), P6204: (2, True)}


def test_ambiguous_alias_never_auto_confirms(client, chat, demo_db):
    for part in (P6205, P6205, P6204, P6204):
        _confirm(client, _card(chat, "3호기 베어링 두 개 씀"), part_id=str(part))
    assert all(ambiguous for _, ambiguous in _aliases(demo_db, "베어링").values())
    assert _card(chat, "3호기 베어링 두 개 씀")["type"] == "select"


def test_select_rejects_part_outside_candidates(client, chat):
    res = _confirm(
        client, _card(chat, "3호기 베어링 두 개 씀"), part_id=str(demo_id("part", "oil"))
    )
    assert res.status_code == 422
    assert res.json()["code"] == "PART_NOT_RESOLVED"


def test_select_without_choice_is_part_not_resolved(client, chat):
    assert _confirm(client, _card(chat, "3호기 베어링 두 개 씀")).status_code == 422


def test_second_confirm_is_409(client, chat):
    card = _card(chat, "베어링 작은 거 2개 씀")
    assert _confirm(client, card).status_code == 200
    res = _confirm(client, card)
    assert res.status_code == 409
    assert res.json()["code"] == "ALREADY_CONFIRMED"


def test_expired_card_is_410(client, chat, monkeypatch):
    card = _card(chat, "베어링 작은 거 2개 씀")
    later = clock.utcnow() + timedelta(minutes=11)
    monkeypatch.setattr(clock, "utcnow", lambda: later)
    res = _confirm(client, card)
    assert res.status_code == 410
    assert res.json()["code"] == "ENTRY_EXPIRED"


def test_other_user_cannot_confirm_or_cancel(client, chat):
    card = _card(chat, "베어링 작은 거 2개 씀")
    assert _confirm(client, card, user="worker2").status_code == 404
    assert _cancel(client, card, user="worker2").status_code == 404


def test_cancel_keeps_ledger_and_blocks_confirm(client, chat, demo_db):
    card = _card(chat, "베어링 작은 거 2개 씀")
    with Session(demo_db.admin) as s:
        before = len(s.scalars(select(Movement.id)).all())
    res = _cancel(client, card)
    assert res.json() == {"entry_id": card["entry_id"], "status": "cancelled"}
    assert _confirm(client, card).status_code == 409
    with Session(demo_db.admin) as s:
        assert len(s.scalars(select(Movement.id)).all()) == before


def test_form_card_cannot_be_confirmed_here(client, chat):
    assert _confirm(client, _card(chat, "타임아웃"), part_id=str(P6205), qty=1).status_code == 400


@pytest.mark.parametrize("qty", [0, -1])
def test_non_positive_qty_is_400(client, chat, qty):
    assert _confirm(client, _card(chat, "베어링 작은 거 2개 씀"), qty=qty).status_code == 400


def test_confirmed_movement_links_source_message(client, chat, demo_db):
    sent = chat("베어링 작은 거 2개 씀").json()
    body = _confirm(client, sent["cards"][0]).json()
    with Session(demo_db.admin) as s:
        movement = s.get(Movement, body["movement"]["id"])
    assert str(movement.message_id) == sent["message_id"]
