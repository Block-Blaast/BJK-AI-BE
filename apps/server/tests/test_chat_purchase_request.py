from concurrent.futures import Executor, Future

import pytest
from bjk_server.chat.interpreter import Interpretation
from bjk_server.db.models import ChatEntry, Review
from bjk_server.reviews.service import ReviewRunner, get_review_runner
from bjk_server.seed.demo import demo_id
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from .chat_fakes import PARSED
from .conftest import auth_header

A42 = demo_id("part", "a42")
SUPPLIER_A = demo_id("supplier", "a")
SUPPLIER_B = demo_id("supplier", "b")
WORKER = demo_id("user", "worker")

PARSED.update(
    {
        "V벨트 30개 시켜주세요, 저번 데서요": Interpretation(
            "PURCHASE_REQUEST", "V벨트 A-42", 30, supplier_text="저번 데"
        ),
        "V벨트 30개 공급사 B로 18000원에": Interpretation(
            "PURCHASE_REQUEST", "V벨트 A-42", 30, supplier_text="공급사 B", unit_price=18000
        ),
        "V벨트 30개 모르는상사": Interpretation(
            "PURCHASE_REQUEST", "V벨트 A-42", 30, supplier_text="모르는상사"
        ),
        "베어링 10개 시켜줘": Interpretation("PURCHASE_REQUEST", "베어링", 10),
        "기어 3개 시켜줘": Interpretation("PURCHASE_REQUEST", "기어", 3),
    }
)


class _Inline(Executor):
    def submit(self, fn, /, *args, **kwargs):
        future: Future = Future()
        future.set_result(fn(*args, **kwargs))
        return future


@pytest.fixture
def reviews(client, demo_db):
    """검토를 커밋 직후 같은 스레드에서 돌린다(ai 없음 → 양식 의견서)."""
    scope = sessionmaker(demo_db.app, expire_on_commit=False).begin
    client.app.dependency_overrides[get_review_runner] = lambda: ReviewRunner(
        scope, None, _Inline()
    )
    yield
    client.app.dependency_overrides.pop(get_review_runner, None)


def _confirm(client, entry_id, **body):
    return client.post(
        f"/api/v1/chat/entries/{entry_id}/confirm", json=body, headers=auth_header("worker")
    )


def _review(demo_db, review_id) -> Review:
    with Session(demo_db.admin) as s:
        return s.get(Review, review_id)


def test_card_resolves_last_order_expression_to_default_supplier(chat):
    body = chat("V벨트 30개 시켜주세요, 저번 데서요").json()
    assert body["intent"] == "PURCHASE_REQUEST"
    [card] = body["cards"]
    assert (card["type"], card["part_id"], card["qty"]) == ("confirm", str(A42), 30)
    assert card["supplier_resolution"] == {
        "text": "저번 데",
        "supplier_id": str(SUPPLIER_A),
        "name": "공급사 A",
        "method": "default",
    }
    assert body["reply"] == "V벨트 A-42 30개, 공급사 A로 요청하셨나요?"


def test_named_supplier_and_unknown_supplier(chat):
    card = chat("V벨트 30개 공급사 B로 18000원에").json()["cards"][0]
    assert card["supplier_resolution"]["method"] == "named"
    assert card["supplier_resolution"]["supplier_id"] == str(SUPPLIER_B)
    assert card["unit_price"] == 18000
    unknown = chat("V벨트 30개 모르는상사").json()["cards"][0]["supplier_resolution"]
    assert (unknown["method"], unknown["supplier_id"]) == ("none", None)


def test_confirm_creates_staff_request_review(chat, client, demo_db, reviews):
    message = chat("V벨트 30개 공급사 B로 18000원에").json()
    res = _confirm(client, message["cards"][0]["entry_id"])
    assert res.status_code == 200, res.text
    body = res.json()
    assert (body["intent"], body["status"]) == ("PURCHASE_REQUEST", "reviewing")
    assert body["reply"] == "검토해서 사장님께 올렸어요."
    review = _review(demo_db, body["review_id"])
    assert (review.entry, review.part_id, review.requested_by) == ("staff_request", A42, WORKER)
    assert str(review.source_message_id) == message["message_id"]
    assert review.request["qty"] == 30
    assert review.request["supplier_id"] == str(SUPPLIER_B)
    assert review.request["unit_price"] == 18000
    assert review.status in ("reviewed", "held")
    assert review.verdict is not None
    again = _confirm(client, message["cards"][0]["entry_id"])
    assert again.status_code == 409


def test_select_card_needs_candidate_and_uses_its_default_supplier(chat, client, demo_db, reviews):
    card = chat("베어링 10개 시켜줘").json()["cards"][0]
    assert card["type"] == "select"
    assert _confirm(client, card["entry_id"]).status_code == 422
    part_id = card["candidates"][0]["part_id"]
    body = _confirm(client, card["entry_id"], part_id=part_id).json()
    review = _review(demo_db, body["review_id"])
    assert str(review.part_id) == part_id
    assert review.request["supplier_id"] == str(SUPPLIER_A)


def test_unregistered_part_has_no_card(chat):
    body = chat("기어 3개 시켜줘").json()
    assert body["cards"] == []
    assert "등록되지 않은 부품" in body["reply"]


def test_form_purchase_request_is_idempotent(client, demo_db, reviews):
    demo_db.reseed()
    form = {
        "client_message_id": "f-pr-1",
        "type": "PURCHASE_REQUEST",
        "part_id": str(A42),
        "qty": 30,
        "supplier_id": str(SUPPLIER_A),
        "unit_price": 18000,
    }
    first = client.post("/api/v1/chat/entries", json=form, headers=auth_header("worker"))
    assert first.status_code == 200, first.text
    again = client.post("/api/v1/chat/entries", json=form, headers=auth_header("worker"))
    assert again.json() == first.json()
    assert first.json()["status"] == "reviewing"
    with Session(demo_db.admin) as s:
        assert s.scalar(select(func.count()).select_from(Review)) == 1
        entry = s.scalar(select(ChatEntry).where(ChatEntry.intent == "PURCHASE_REQUEST"))
        assert (entry.type, entry.status) == ("form", "confirmed")
    missing = dict(form, client_message_id="f-pr-2", supplier_id=str(A42))
    res = client.post("/api/v1/chat/entries", json=missing, headers=auth_header("worker"))
    assert res.status_code == 404
