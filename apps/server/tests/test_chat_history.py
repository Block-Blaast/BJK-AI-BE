from datetime import timedelta

from bjk_server import clock

from .conftest import auth_header

URL = "/api/v1/chat/messages"


def _history(client, user="worker", **params):
    return client.get(URL, params=params, headers=auth_header(user))


def test_history_lists_own_messages_newest_first_with_card_status(client, chat):
    first = chat("베어링 작은 거 2개 씀").json()
    second = chat("V벨트 3개 들어옴").json()
    chat("안녕")
    client.post(
        f"/api/v1/chat/entries/{first['cards'][0]['entry_id']}/confirm",
        json={},
        headers=auth_header("worker"),
    )
    client.post(
        f"/api/v1/chat/entries/{second['cards'][0]['entry_id']}/cancel",
        headers=auth_header("worker"),
    )

    res = _history(client)
    assert res.status_code == 200
    items = res.json()["items"]
    assert [i["text"] for i in items] == ["안녕", "V벨트 3개 들어옴", "베어링 작은 거 2개 씀"]
    assert items[0]["cards"] == []
    assert items[1]["cards"][0]["status"] == "cancelled"
    assert items[2]["cards"][0]["status"] == "confirmed"
    assert items[2]["reply"] == "볼베어링 6205ZZ 2개 출고할까요?"


def test_open_card_past_ttl_shows_expired(client, chat, monkeypatch):
    chat("베어링 작은 거 2개 씀")
    later = clock.utcnow() + timedelta(minutes=11)
    monkeypatch.setattr(clock, "utcnow", lambda: later)
    assert _history(client).json()["items"][0]["cards"][0]["status"] == "expired"


def test_other_users_messages_are_not_included(client, chat):
    chat("안녕", user="worker2")
    chat("V벨트 3개 들어옴")
    assert [i["text"] for i in _history(client).json()["items"]] == ["V벨트 3개 들어옴"]
    assert [i["text"] for i in _history(client, user="worker2").json()["items"]] == ["안녕"]


def test_cursor_pages_newest_first(client, chat):
    for _ in range(3):
        chat("안녕")
    page1 = _history(client, limit=2).json()
    page2 = _history(client, limit=2, cursor=page1["next_cursor"]).json()
    ids = [i["message_id"] for i in page1["items"] + page2["items"]]
    assert len(ids) == len(set(ids)) == 3
    assert page2["next_cursor"] is None


def test_requires_login(client):
    assert client.get(URL).status_code == 401
