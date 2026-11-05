import uuid

import httpx
import pytest
from bjk_contracts import AiMeta, ChatParseResponse, EmbedTask, FallbackReason, LlmPurpose
from bjk_server.ai.client import AiUnavailable
from bjk_server.ai.embeddings import AiQueryEmbedder
from bjk_server.chat.interpreter import AiInterpreter, Interpretation, InterpreterUnavailable
from bjk_server.chat.records import to_base_qty

from .ai_fakes import EMBED_MODEL, FakeAi, parse_failed, parsed, usage, vector

COMPANY = uuid.uuid4()


def test_health_passes_ai_llm_status():
    ai = FakeAi()
    assert ai.client().health() == "ok"
    ai.llm = "not_configured"
    assert ai.client().health() == "not_configured"
    assert FakeAi(fail=500).client().health() == "error"
    assert FakeAi(fail=httpx.ConnectError("refused")).client().health() == "error"


def test_parse_chat_sends_contract_request_and_reads_response():
    ai = FakeAi(chat={"볼트 3개 씀": parsed("OUT", part_text="볼트", qty=3, unit="개")})
    result = ai.client().parse_chat(COMPANY, "볼트 3개 씀")
    assert ai.requests == [("/v1/chat/parse", {"company_id": str(COMPANY), "text": "볼트 3개 씀"})]
    assert result.intent == "OUT" and result.items[0].qty == 3


@pytest.mark.parametrize(
    ("fail", "reason"),
    [
        (httpx.ReadTimeout("slow"), FallbackReason.TIMEOUT),
        (httpx.ConnectError("refused"), FallbackReason.ERROR),
        (422, FallbackReason.ERROR),
        (500, FallbackReason.ERROR),
    ],
)
def test_http_failure_becomes_fallback_reason(fail, reason):
    with pytest.raises(AiUnavailable) as exc:
        FakeAi(fail=fail).client().parse_chat(COMPANY, "볼트 3개 씀")
    assert exc.value.reason == reason


def test_response_outside_contract_is_schema_invalid():
    def handler(request):
        return httpx.Response(200, json={"intent": "OUT", "items": []})  # ai 객체 없음

    client = FakeAi().client()
    client._http = httpx.Client(base_url="http://ai", transport=httpx.MockTransport(handler))
    with pytest.raises(AiUnavailable) as exc:
        client.parse_chat(COMPANY, "볼트 3개 씀")
    assert exc.value.reason == FallbackReason.SCHEMA_INVALID


def _interpreter(ai: FakeAi) -> tuple[AiInterpreter, list]:
    usages: list = []
    return AiInterpreter(ai.client(), COMPANY, usages.append), usages


def test_interpreter_keeps_every_item_and_reports_usage():
    response = ChatParseResponse(
        intent="OUT",
        items=[
            {"part_text": "볼트", "qty": 2, "unit": "박스", "equipment_text": "3호기"},
            {"part_text": "너트", "qty": 200},
        ],
        ai=AiMeta.ok(),
        usage=usage(LlmPurpose.CHAT_PARSE),
    )
    interpreter, usages = _interpreter(FakeAi(chat={"t": response}))
    assert interpreter.interpret("t") == Interpretation(
        "OUT",
        part_text="볼트",
        qty=2,
        equipment_text="3호기",
        unit="박스",
        more=(Interpretation("OUT", part_text="너트", qty=200),),
    )
    assert [u.purpose for u in usages] == [LlmPurpose.CHAT_PARSE]


def test_interpreter_without_items_keeps_intent():
    interpreter, _ = _interpreter(FakeAi(chat={"안녕": parsed("OTHER")}))
    assert interpreter.interpret("안녕") == Interpretation("OTHER")


@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        (FallbackReason.TIMEOUT, "timeout"),
        (FallbackReason.SCHEMA_INVALID, "schema_invalid"),
        (FallbackReason.QUOTA_EXCEEDED, "quota_exceeded"),
        (FallbackReason.VERIFY_FAILED, "error"),
    ],
)
def test_interpreter_fallback_response_keeps_reason_and_usage(reason, expected):
    interpreter, usages = _interpreter(FakeAi(chat={"t": parse_failed(reason)}))
    with pytest.raises(InterpreterUnavailable) as exc:
        interpreter.interpret("t")
    assert exc.value.reason == expected
    assert [u.success for u in usages] == [False]


def test_interpreter_http_failure_has_no_usage():
    interpreter, usages = _interpreter(FakeAi(fail=httpx.ReadTimeout("slow")))
    with pytest.raises(InterpreterUnavailable) as exc:
        interpreter.interpret("t")
    assert (exc.value.reason, usages) == ("timeout", [])


def test_query_embedder_returns_model_and_vector():
    ai = FakeAi(vectors={"헥사볼트": vector({0: 1.0})})
    usages: list = []
    result = AiQueryEmbedder(ai.client(), COMPANY, usages.append).embed_query("헥사볼트")
    assert result == (EMBED_MODEL, vector({0: 1.0}))
    assert ai.requests[0][1]["task"] == EmbedTask.QUERY
    assert len(usages) == 1


def test_query_embedder_failure_is_none():
    ai = FakeAi()
    ai.embed_fallback = True
    assert AiQueryEmbedder(ai.client(), COMPANY, lambda u: None).embed_query("볼트") is None
    timeout = FakeAi(fail=httpx.ReadTimeout("slow"))
    assert AiQueryEmbedder(timeout.client(), COMPANY, lambda u: None).embed_query("볼트") is None


@pytest.mark.parametrize(
    ("qty", "unit", "pack_qty", "expected"),
    [
        (2, "박스", 100, 200),
        (2, " BOX ", 50, 100),
        (2, "박스", None, None),
        (3, "개", 100, 3),
        (3, None, 100, 3),
        (None, "박스", 100, None),
    ],
)
def test_box_unit_multiplies_pack_qty(qty, unit, pack_qty, expected):
    assert to_base_qty(qty, unit, pack_qty) == expected
