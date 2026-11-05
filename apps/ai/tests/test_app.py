import asyncio
import json
import math

import pytest
from bjk_ai.config import Settings
from bjk_ai.embedding import format_text
from bjk_ai.gateway import EmbedResult, GenerateResult
from bjk_ai.main import create_app
from bjk_contracts import EMBEDDING_DIM, EmbedTask
from fastapi.testclient import TestClient

COMPANY_ID = "6f1c2f9e-6d1a-4c3e-9a51-2b7f0c8d4e11"


class FakeGateway:
    """응답을 순서대로 돌려준다. 예외 객체면 던지고, 숫자면 그만큼 기다린다."""

    def __init__(self, *, texts=(), vectors=()):
        self.texts = list(texts)
        self.vectors = list(vectors)
        self.generate_calls = []
        self.embed_calls = []

    async def generate_json(self, *, model, system, prompt, schema):
        self.generate_calls.append(prompt)
        return GenerateResult(text=await self._next(self.texts), input_tokens=10, output_tokens=5)

    async def embed(self, *, model, texts, dim):
        self.embed_calls.append((texts, dim))
        return EmbedResult(vectors=await self._next(self.vectors), input_tokens=0)

    @staticmethod
    async def _next(queue):
        value = queue.pop(0)
        if isinstance(value, BaseException):
            raise value
        if isinstance(value, float):
            await asyncio.sleep(value)
        return value


def make_client(gateway=None, **overrides):
    settings = Settings(_env_file=None, gemini_api_key=None, **overrides)
    return TestClient(create_app(settings=settings, gateway=gateway))


def llm_json(intent, items=()):
    return json.dumps({"intent": intent, "items": list(items)}, ensure_ascii=False)


def parse(client, text):
    return client.post("/v1/chat/parse", json={"company_id": COMPANY_ID, "text": text})


def embed(client, texts, task="document"):
    return client.post(
        "/v1/embeddings", json={"company_id": COMPANY_ID, "task": task, "texts": texts}
    )


def test_health_reports_llm_configuration():
    with make_client() as client:
        assert client.get("/health").json() == {"status": "ok", "llm": "not_configured"}
    with make_client(FakeGateway()) as client:
        assert client.get("/health").json() == {"status": "ok", "llm": "ok"}


def test_chat_parse_splits_items_and_cleans_text():
    gateway = FakeGateway(
        texts=[
            llm_json(
                "OUT",
                [
                    {"part_text": " 볼트 ", "qty": 200, "unit": "개", "note": ""},
                    {"part_text": "너트", "qty": 200, "unit": "개"},
                ],
            )
        ]
    )
    with make_client(gateway) as client:
        body = parse(client, "볼트 200개, 너트 200개 씀").json()

    assert body["intent"] == "OUT"
    assert body["items"][0] == {
        "part_text": "볼트",
        "qty": 200,
        "unit": "개",
        "equipment_text": None,
        "supplier_text": None,
        "unit_price": None,
        "note": None,
    }
    assert body["items"][1]["part_text"] == "너트"
    assert body["ai"] == {"used": True, "fallback": False, "reason": None}
    assert body["usage"]["attempts"] == 1
    assert body["usage"]["input_tokens"] == 10
    assert gateway.generate_calls == ["볼트 200개, 너트 200개 씀"]


def test_chat_parse_drops_items_for_other():
    gateway = FakeGateway(texts=[llm_json("OTHER", [{"part_text": "날씨"}])])
    with make_client(gateway) as client:
        body = parse(client, "오늘 날씨 어때").json()

    assert body["intent"] == "OTHER"
    assert body["items"] == []


def test_chat_parse_retries_once_after_invalid_json():
    gateway = FakeGateway(
        texts=["{not json", llm_json("PURCHASE_REQUEST", [{"part_text": "V벨트", "qty": 30}])]
    )
    with make_client(gateway) as client:
        body = parse(client, "V벨트 30개 시켜주세요").json()

    assert body["intent"] == "PURCHASE_REQUEST"
    assert body["usage"]["attempts"] == 2
    assert body["usage"]["input_tokens"] == 20


@pytest.mark.parametrize(
    ("responses", "reason"),
    [
        (["{not json", llm_json("BUY")], "schema_invalid"),
        ([llm_json("OUT", [{"qty": -1}]), llm_json("OUT", [{"qty": -2}])], "schema_invalid"),
        ([RuntimeError("down"), RuntimeError("down")], "error"),
    ],
)
def test_chat_parse_falls_back_after_two_failures(responses, reason):
    gateway = FakeGateway(texts=responses)
    with make_client(gateway) as client:
        response = parse(client, "베어링 두 개 씀")

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] is None
    assert body["items"] == []
    assert body["ai"] == {"used": True, "fallback": True, "reason": reason}
    assert body["usage"]["success"] is False
    assert body["usage"]["attempts"] == 2


def test_chat_parse_times_out_within_budget():
    gateway = FakeGateway(texts=[1.0, 1.0])
    with make_client(gateway, chat_budget_seconds=0.05) as client:
        body = parse(client, "베어링 두 개 씀").json()

    assert body["ai"]["reason"] == "timeout"
    assert body["usage"]["latency_ms"] < 1000


def test_chat_parse_without_api_key_skips_llm():
    with make_client() as client:
        body = parse(client, "베어링 두 개 씀").json()

    assert body["ai"] == {"used": False, "fallback": True, "reason": "error"}
    assert body["usage"] is None


def test_chat_parse_rejects_text_over_500():
    with make_client(FakeGateway()) as client:
        assert parse(client, "가" * 501).status_code == 422


def unit_vector(index):
    vector = [0.0] * EMBEDDING_DIM
    vector[index] = 2.0
    return vector


def test_embeddings_format_by_task_and_normalize():
    gateway = FakeGateway(vectors=[[unit_vector(0), unit_vector(1)]])
    with make_client(gateway) as client:
        body = embed(client, ["육각볼트 M8-20", "헥사볼트 M8×20"]).json()

    texts, dim = gateway.embed_calls[0]
    assert texts == ["title: none | text: 육각볼트 M8-20", "title: none | text: 헥사볼트 M8×20"]
    assert dim == EMBEDDING_DIM
    assert body["model"] == "gemini-embedding-2"
    assert len(body["vectors"]) == 2
    assert math.isclose(sum(v * v for v in body["vectors"][0]), 1.0)
    assert body["vectors"][0][0] == 1.0


def test_query_format():
    assert format_text(EmbedTask.QUERY, " 베아링 ") == "task: search result | query: 베아링"


@pytest.mark.parametrize(
    "bad",
    [
        [[0.0] * 768],
        [unit_vector(0), unit_vector(1)],
        [[0.0] * EMBEDDING_DIM],
    ],
    ids=["wrong_dim", "count_mismatch", "zero_vector"],
)
def test_embeddings_fall_back_on_bad_vectors(bad):
    gateway = FakeGateway(vectors=[bad, bad])
    with make_client(gateway) as client:
        body = embed(client, ["볼트"]).json()

    assert body["vectors"] is None
    assert body["model"] is None
    assert body["ai"] == {"used": True, "fallback": True, "reason": "schema_invalid"}


def test_embeddings_without_api_key_skips_llm():
    with make_client() as client:
        body = embed(client, ["볼트"], task="query").json()

    assert body["ai"]["fallback"] is True
    assert body["usage"] is None
