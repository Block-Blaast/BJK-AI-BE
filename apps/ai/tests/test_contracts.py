from uuid import uuid4

import pytest
from bjk_contracts import (
    EMBEDDING_DIM,
    AiMeta,
    ChatIntent,
    ChatParseRequest,
    ChatParseResponse,
    EmbedRequest,
    EmbedResponse,
    EmbedTask,
    FallbackReason,
    ParsedItem,
)
from pydantic import ValidationError


def test_ai_meta_matches_api_spec_shape():
    assert AiMeta.ok().model_dump(mode="json") == {"used": True, "fallback": False, "reason": None}
    assert AiMeta.failed(FallbackReason.TIMEOUT).model_dump(mode="json") == {
        "used": True,
        "fallback": True,
        "reason": "timeout",
    }


def test_ai_meta_rejects_reason_without_fallback():
    with pytest.raises(ValidationError):
        AiMeta(used=True, fallback=False, reason=FallbackReason.ERROR)
    with pytest.raises(ValidationError):
        AiMeta(used=True, fallback=True)


def test_chat_request_rejects_text_over_500():
    ChatParseRequest(company_id=uuid4(), text="가" * 500)
    with pytest.raises(ValidationError):
        ChatParseRequest(company_id=uuid4(), text="가" * 501)


def test_chat_response_multiple_items():
    response = ChatParseResponse(
        intent=ChatIntent.OUT,
        items=[
            ParsedItem(part_text="볼트", qty=200, unit="개"),
            ParsedItem(part_text="너트", qty=200, unit="개"),
        ],
        ai=AiMeta.ok(),
    )

    dumped = response.model_dump(mode="json")
    assert dumped["intent"] == "OUT"
    assert [item["part_text"] for item in dumped["items"]] == ["볼트", "너트"]


def test_chat_response_fallback_carries_no_result():
    ChatParseResponse(intent=None, ai=AiMeta.failed(FallbackReason.SCHEMA_INVALID))
    with pytest.raises(ValidationError):
        ChatParseResponse(
            intent=ChatIntent.OUT,
            items=[ParsedItem(part_text="볼트")],
            ai=AiMeta.failed(FallbackReason.ERROR),
        )
    with pytest.raises(ValidationError):
        ChatParseResponse(intent=None, ai=AiMeta.ok())


def test_embed_request_rejects_blank_text():
    EmbedRequest(company_id=uuid4(), task=EmbedTask.DOCUMENT, texts=["육각볼트 M8-20"])
    with pytest.raises(ValidationError):
        EmbedRequest(company_id=uuid4(), task=EmbedTask.QUERY, texts=["  "])
    with pytest.raises(ValidationError):
        EmbedRequest(company_id=uuid4(), task=EmbedTask.QUERY, texts=[])


def test_embed_response_requires_embedding_dim():
    EmbedResponse(model="m", vectors=[[0.0] * EMBEDDING_DIM], ai=AiMeta.ok())
    with pytest.raises(ValidationError):
        EmbedResponse(model="m", vectors=[[0.0] * 768], ai=AiMeta.ok())


def test_embed_response_fallback_has_no_vectors():
    EmbedResponse(model=None, vectors=None, ai=AiMeta.failed(FallbackReason.TIMEOUT))
    with pytest.raises(ValidationError):
        EmbedResponse(model=None, vectors=None, ai=AiMeta.ok())
