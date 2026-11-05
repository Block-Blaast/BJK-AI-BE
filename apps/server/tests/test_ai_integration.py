"""server ↔ ai 연동: 계약 응답으로 채팅 카드·매칭·임베딩 저장·호출 기록 (docs/ai-integration.md)."""

from datetime import UTC, datetime

import httpx
import pytest
from bjk_contracts import EMBEDDING_DIM, FallbackReason
from bjk_server import ratelimit
from bjk_server.ai.client import get_ai_client
from bjk_server.db.models import LlmCall, Part, PartAlias
from bjk_server.jobs import nightly as nightly_job
from bjk_server.jobs.runner import run_job
from bjk_server.seed.demo import demo_id
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .ai_fakes import EMBED_MODEL, FakeAi, parse_failed, parsed, vector
from .conftest import auth_header

CHAT_URL = "/api/v1/chat/messages"
NOW = datetime(2026, 11, 4, 1, 0, 0, tzinfo=UTC)
BOLT = demo_id("part", "m820")
ORING = demo_id("part", "p20")


@pytest.fixture
def ai(client, demo_db, monkeypatch):
    """시드를 다시 넣고 server가 가짜 ai를 부르게 한다."""
    demo_db.reseed()
    monkeypatch.setattr(ratelimit, "utcnow", lambda: NOW)
    fake = FakeAi()
    client.app.dependency_overrides[get_ai_client] = fake.client
    return fake


def _send(client, text, user="worker"):
    body = {"client_message_id": f"ai-{text}", "text": text}
    return client.post(CHAT_URL, json=body, headers=auth_header(user))


def _calls(demo_db) -> list[tuple[str, bool]]:
    with Session(demo_db.admin) as s:
        rows = s.execute(select(LlmCall.purpose, LlmCall.success).order_by(LlmCall.created_at))
        return [tuple(r) for r in rows]


def _embed_parts(demo_db, vectors: dict) -> None:
    with Session(demo_db.admin) as s, s.begin():
        for part_id, values in vectors.items():
            s.execute(
                update(Part)
                .where(Part.id == part_id)
                .values(embedding=values, embedding_model=EMBED_MODEL)
            )


def test_chat_uses_ai_parse_and_converts_boxes(client, demo_db, ai):
    ai.chat["육각볼트 M8-20 2박스 들어옴"] = parsed(
        "IN", part_text="육각볼트 M8-20", qty=2, unit="박스"
    )
    body = _send(client, "육각볼트 M8-20 2박스 들어옴").json()
    assert body["ai"] == {"used": True, "fallback": False, "reason": None}
    card = body["cards"][0]
    assert (card["type"], card["part_id"], card["qty"]) == ("confirm", str(BOLT), 200)
    assert ai.paths() == ["/v1/chat/parse", "/v1/embeddings"]
    assert _calls(demo_db) == [("chat_parse", True), ("embedding", True)]

    res = client.post(
        f"/api/v1/chat/entries/{card['entry_id']}/confirm", json={}, headers=auth_header("worker")
    )
    assert res.json()["movement"]["qty"] == 200


def test_box_unit_on_select_card_converts_with_chosen_part(client, demo_db, ai):
    ai.chat["볼트 1박스 씀"] = parsed("OUT", part_text="볼트", qty=1, unit="박스")
    card = _send(client, "볼트 1박스 씀").json()["cards"][0]
    assert card["type"] == "select"
    res = client.post(
        f"/api/v1/chat/entries/{card['entry_id']}/confirm",
        json={"part_id": str(BOLT)},
        headers=auth_header("worker"),
    )
    assert res.json()["movement"]["qty"] == -100  # 출고는 음수


def test_ai_fallback_response_gives_form_card_and_records_usage(client, demo_db, ai):
    ai.chat["볼트 3개 씀"] = parse_failed(FallbackReason.TIMEOUT)
    body = _send(client, "볼트 3개 씀").json()
    assert body["ai"] == {"used": True, "fallback": True, "reason": "timeout"}
    assert [c["type"] for c in body["cards"]] == ["form"]
    assert _calls(demo_db) == [("chat_parse", False)]


def test_ai_unreachable_gives_form_card_without_usage(client, demo_db, ai):
    ai.fail = httpx.ConnectError("connection refused")
    body = _send(client, "볼트 3개 씀").json()
    assert body["ai"]["reason"] == "error"
    assert [c["type"] for c in body["cards"]] == ["form"]
    assert _calls(demo_db) == []


def test_meaning_confirms_part_spelling_misses(client, demo_db, ai):
    _embed_parts(demo_db, {BOLT: vector({0: 1.0}), ORING: vector({1: 1.0})})
    ai.vectors["hex bolt"] = vector({0: 0.95, 1: 0.05})
    ai.chat["hex bolt 5개 씀"] = parsed("OUT", part_text="hex bolt", qty=5)
    card = _send(client, "hex bolt 5개 씀").json()["cards"][0]
    assert (card["type"], card["part_id"]) == ("confirm", str(BOLT))


def test_close_meanings_give_semantic_candidates(client, demo_db, ai):
    _embed_parts(demo_db, {BOLT: vector({0: 1.0}), ORING: vector({0: 0.9, 1: 0.44})})
    ai.vectors["hex bolt"] = vector({0: 1.0, 1: 0.2})
    ai.chat["hex bolt 5개 씀"] = parsed("OUT", part_text="hex bolt", qty=5)
    card = _send(client, "hex bolt 5개 씀").json()["cards"][0]
    assert card["type"] == "select"
    assert [(c["part_id"], c["reason"]) for c in card["candidates"]] == [
        (str(BOLT), "semantic"),
        (str(ORING), "semantic"),
    ]


def test_meaning_never_overrides_spec_conflict(client, demo_db, ai):
    _embed_parts(demo_db, {BOLT: vector({0: 1.0})})
    ai.vectors["hex bolt M8x30"] = vector({0: 1.0})
    ai.chat["hex bolt M8x30 5개 씀"] = parsed("OUT", part_text="hex bolt M8x30", qty=5)
    card = _send(client, "hex bolt M8x30 5개 씀").json()["cards"][0]
    assert card["type"] == "unregistered"


def test_query_embedding_failure_keeps_spelling_match(client, demo_db, ai):
    ai.embed_fallback = True
    ai.chat["베아링 2개 씀"] = parsed("OUT", part_text="베아링", qty=2)
    card = _send(client, "베아링 2개 씀").json()["cards"][0]
    assert card["type"] == "select"
    assert {c["reason"] for c in card["candidates"]} <= {"name", "equipment_part"}


def _create(client, name):
    return client.post(
        "/api/v1/parts", json={"name": name, "unit": "개"}, headers=auth_header("manager")
    )


def _embedding(demo_db, part_id):
    with Session(demo_db.admin) as s:
        part = s.get(Part, part_id)
        return part.embedding, part.embedding_model


def test_part_registration_stores_document_embedding(client, demo_db, ai):
    part = _create(client, "평와셔 M8").json()
    values, model = _embedding(demo_db, part["id"])
    assert (len(values), model) == (EMBEDDING_DIM, EMBED_MODEL)
    assert ai.requests[-1][1]["task"] == "document"
    assert ai.requests[-1][1]["texts"] == ["평와셔 M8"]
    assert _calls(demo_db) == [("embedding", True)]


def test_rename_replaces_embedding(client, demo_db, ai):
    part = _create(client, "평와셔 M8").json()
    ai.vectors["평와셔 M10"] = vector({5: 1.0})
    client.patch(
        f"/api/v1/parts/{part['id']}", json={"name": "평와셔 M10"}, headers=auth_header("manager")
    )
    values, _ = _embedding(demo_db, part["id"])
    assert list(values) == pytest.approx(vector({5: 1.0}))
    client.patch(
        f"/api/v1/parts/{part['id']}", json={"location": "A"}, headers=auth_header("manager")
    )
    assert ai.paths().count("/v1/embeddings") == 2


def test_registration_without_ai_answer_leaves_embedding_empty(client, demo_db, ai):
    ai.fail = 500
    res = _create(client, "평와셔 M8")
    assert res.status_code == 201
    assert _embedding(demo_db, res.json()["id"]) == (None, None)


def test_nightly_fills_missing_embeddings(demo_db, monkeypatch):
    demo_db.reseed()
    fake = FakeAi()
    monkeypatch.setattr(nightly_job, "get_ai_client", fake.client)
    with Session(demo_db.admin) as s:
        parts = len(s.scalars(select(Part).where(Part.merged_into.is_(None))).all())
        aliases = len(s.scalars(select(PartAlias)).all())
    result = run_job(demo_db.app, "nightly", "manual", now=NOW)
    assert result.status == "ok", result.error
    assert result.summary["embeddings_filled"] == parts + aliases
    with Session(demo_db.admin) as s:
        assert s.scalar(select(Part).where(Part.embedding.is_(None))) is None
        assert {c.purpose for c in s.scalars(select(LlmCall))} == {"embedding"}
    # 다시 돌리면 채울 것이 없다.
    assert run_job(demo_db.app, "nightly", "manual", now=NOW).summary["embeddings_filled"] == 0
