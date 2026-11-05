from dataclasses import replace

from bjk_server.chat.interpreter import Interpretation

from .chat_fakes import PARSED
from .conftest import auth_header

PARSED.update(
    {
        "6205 1개, V벨트 3개 씀": replace(
            PARSED["6205 1개 씀"], more=(Interpretation("OUT", "V벨트", 3),)
        ),
        "6205 1개, 기어 하나 씀": replace(
            PARSED["6205 1개 씀"], more=(Interpretation("OUT", "기어", 1),)
        ),
    }
)


def test_each_item_gets_its_own_card(chat):
    single = chat("6205 1개 씀").json()
    body = chat("6205 1개, V벨트 3개 씀").json()
    assert body["intent"] == "OUT"
    first, second = body["cards"]
    assert (first["part_text"], first["qty"]) == ("6205", 1)
    assert (second["part_text"], second["qty"]) == ("V벨트", 3)
    assert first["entry_id"] != second["entry_id"]
    assert body["reply"].split("\n")[0] == single["reply"]
    assert len(body["reply"].split("\n")) == 2


def test_cards_are_confirmed_one_by_one(chat, client):
    first, unregistered = chat("6205 1개, 기어 하나 씀").json()["cards"]
    assert unregistered["type"] == "unregistered"
    res = client.post(
        f"/api/v1/chat/entries/{first['entry_id']}/confirm",
        json={},
        headers=auth_header("worker"),
    )
    assert res.status_code == 200, res.text
    assert res.json()["movement"]["qty"] == -1
