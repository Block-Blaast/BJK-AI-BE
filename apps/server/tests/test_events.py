import json
import threading
import time
import uuid

import pytest
from bjk_server.api import events as events_api
from bjk_server.db.models import Company, ServerEvent
from bjk_server.events import publish
from bjk_server.seed.demo import COMPANY_CODE, demo_id
from sqlalchemy import select
from sqlalchemy.orm import Session

from .conftest import auth_header, build_client

URL = "/api/v1/events"
COMPANY = demo_id("company", COMPANY_CODE)
P6205 = demo_id("part", "6205")


@pytest.fixture
def fresh(demo_db, monkeypatch):
    demo_db.reseed()
    monkeypatch.setattr(events_api, "POLL_SECONDS", 0.05)
    monkeypatch.setattr(events_api, "MAX_STREAM_SECONDS", 1.0)
    monkeypatch.setattr(events_api, "KEEPALIVE_SECONDS", 0.3)
    yield demo_db
    demo_db.reseed()


def _parse(text: str) -> list[dict]:
    found = []
    for block in text.split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        if "event" in fields:
            found.append(
                {
                    "id": int(fields["id"]),
                    "event": fields["event"],
                    "data": json.loads(fields["data"]),
                }
            )
    return found


def _read(client, user="worker", last_event_id=None) -> str:
    headers = auth_header(user) | ({"Last-Event-ID": str(last_event_id)} if last_event_id else {})
    with client.stream("GET", URL, headers=headers) as res:
        assert res.status_code == 200
        assert res.headers["content-type"].startswith("text/event-stream")
        return "".join(res.iter_text())


def _publish(demo_db, company_id, data, type_="stock.changed") -> int:
    with Session(demo_db.admin) as s, s.begin():
        publish(s, company_id, type_, data)
        s.flush()
        return s.scalar(select(ServerEvent.id).order_by(ServerEvent.id.desc()).limit(1))


def _form_out(client):
    body = {
        "client_message_id": f"f-{uuid.uuid4()}",
        "type": "OUT",
        "part_id": str(P6205),
        "qty": 1,
    }
    res = client.post("/api/v1/chat/entries", json=body, headers=auth_header("worker"))
    assert res.status_code == 200
    return res.json()["stock_after"]


def test_form_entry_publishes_stock_changed_to_open_stream(fresh, monkeypatch):
    # 폼 기록 요청이 느린 CI에서도 스트림이 열려 있는 동안 끝나도록 이 테스트만 오래 연다.
    monkeypatch.setattr(events_api, "MAX_STREAM_SECONDS", 5.0)
    client = build_client(fresh)

    def later():
        time.sleep(0.3)
        _form_out(build_client(fresh))

    thread = threading.Thread(target=later)
    thread.start()
    text = _read(client)
    thread.join()
    assert text.startswith("retry: 3000")
    received = _parse(text)
    assert [e["event"] for e in received] == ["stock.changed"]
    assert received[0]["data"] == {"part_id": str(P6205), "stock": 2}


def test_without_last_event_id_only_new_events(client, fresh):
    _publish(fresh, COMPANY, {"part_id": "old", "stock": 1})
    assert _parse(_read(client)) == []


def test_last_event_id_resumes_after_it(client, fresh):
    first = _publish(fresh, COMPANY, {"n": 1})
    second = _publish(fresh, COMPANY, {"n": 2})
    third = _publish(fresh, COMPANY, {"n": 3})
    received = _parse(_read(client, last_event_id=first))
    assert [e["id"] for e in received] == [second, third]
    assert [e["data"]["n"] for e in received] == [2, 3]


def test_other_company_events_are_not_sent(client, fresh):
    other = uuid.uuid4()
    with Session(fresh.admin) as s, s.begin():
        s.add(Company(id=other, name="다른회사", code="OTHER3"))
    _publish(fresh, other, {"n": "other"})
    mine = _publish(fresh, COMPANY, {"n": "mine"})
    received = _parse(_read(client, last_event_id=1))
    assert [e["id"] for e in received] == [mine]


def test_keepalive_comment_when_idle(client, fresh):
    assert ": keepalive" in _read(client)


def test_late_committed_event_is_still_sent_once(fresh):
    """먼저 id를 받았지만 늦게 커밋된 이벤트도 빠짐없이 한 번만 보낸다."""
    client = build_client(fresh)
    holder_ready = threading.Event()

    def slow_writer():
        with Session(fresh.admin) as s, s.begin():
            publish(s, COMPANY, "stock.changed", {"n": "slow"})
            s.flush()  # 작은 id를 먼저 받고
            holder_ready.set()
            time.sleep(0.5)  # 늦게 커밋

    def fast_writer():
        holder_ready.wait()
        time.sleep(0.1)
        _publish(fresh, COMPANY, {"n": "fast"})

    threads = [threading.Thread(target=slow_writer), threading.Thread(target=fast_writer)]
    for t in threads:
        t.start()
    text = _read(client)
    for t in threads:
        t.join()
    assert sorted(e["data"]["n"] for e in _parse(text)) == ["fast", "slow"]


def test_requires_token(client):
    assert client.get(URL).status_code == 401
