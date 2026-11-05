from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from bjk_server import idempotency
from bjk_server.chat.interpreter import get_interpreter
from bjk_server.db.models import ChatMessage, Movement
from bjk_server.seed.demo import demo_id
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .chat_fakes import FakeInterpreter
from .conftest import auth_header


@pytest.mark.parametrize("endpoint", ["messages", "entries"])
@pytest.mark.parametrize("case", ["same", "different-body", "different-user"])
def test_simultaneous_requests_do_not_duplicate_or_leak(
    client, demo_db, monkeypatch, endpoint, case
):
    demo_db.reseed()
    client.app.dependency_overrides[get_interpreter] = FakeInterpreter
    first_claimed = Event()
    second_entered = Event()
    release_first = Event()
    original_claim = idempotency.claim

    def controlled_claim(*args, **kwargs):
        if first_claimed.is_set():
            second_entered.set()
            return original_claim(*args, **kwargs)
        result = original_claim(*args, **kwargs)
        first_claimed.set()
        if not release_first.wait(10):
            raise TimeoutError("두 번째 요청이 시작되지 않았습니다.")
        return result

    monkeypatch.setattr(idempotency, "claim", controlled_claim)
    if endpoint == "messages":
        first_body = {"client_message_id": "concurrent-key", "text": "안녕"}
        second_body = first_body | ({"text": "다른 입력"} if case == "different-body" else {})
        model = ChatMessage
    else:
        first_body = {
            "client_message_id": "concurrent-key",
            "type": "IN",
            "part_id": str(demo_id("part", "6205")),
            "qty": 2,
        }
        second_body = first_body | ({"qty": 3} if case == "different-body" else {})
        model = Movement

    with Session(demo_db.admin) as session:
        before = session.scalar(select(func.count()).select_from(model))

    def send(body, user):
        return client.post(f"/api/v1/chat/{endpoint}", json=body, headers=auth_header(user))

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(send, first_body, "worker")
        try:
            assert first_claimed.wait(10)
            second_future = executor.submit(
                send, second_body, "worker2" if case == "different-user" else "worker"
            )
            assert second_entered.wait(10)
        finally:
            release_first.set()
        first = first_future.result(timeout=15)
        second = second_future.result(timeout=15)

    assert first.status_code == 200
    if case == "same":
        assert second.status_code == 200
        assert second.json() == first.json()
    else:
        assert second.status_code == 409
        assert second.json()["code"] == "IDEMPOTENCY_CONFLICT"
    with Session(demo_db.admin) as session:
        after = session.scalar(select(func.count()).select_from(model))
    assert after == before + 1
