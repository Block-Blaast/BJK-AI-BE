import json
import math

import pytest
from bjk_contracts import EMBEDDING_DIM, EmbedTask


def llm_json(intent, items=()):
    return json.dumps({"intent": intent, "items": list(items)}, ensure_ascii=False)


@pytest.fixture
def parse(company_id):
    def _parse(client, text):
        return client.post("/v1/chat/parse", json={"company_id": company_id, "text": text})

    return _parse


@pytest.fixture
def embed(company_id):
    def _embed(client, texts, task="document"):
        return client.post(
            "/v1/embeddings", json={"company_id": company_id, "task": task, "texts": texts}
        )

    return _embed


def test_health_reports_llm_configuration(make_client, fake_gateway):
    with make_client() as client:
        assert client.get("/health").json() == {"status": "ok", "llm": "not_configured"}
    with make_client(fake_gateway()) as client:
        assert client.get("/health").json() == {"status": "ok", "llm": "ok"}


def test_chat_parse_splits_items_and_cleans_text(make_client, fake_gateway, parse):
    gateway = fake_gateway(
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


def test_chat_parse_drops_items_for_other(make_client, fake_gateway, parse):
    gateway = fake_gateway(texts=[llm_json("OTHER", [{"part_text": "날씨"}])])
    with make_client(gateway) as client:
        body = parse(client, "오늘 날씨 어때").json()

    assert body["intent"] == "OTHER"
    assert body["items"] == []


def test_chat_parse_retries_once_after_invalid_json(make_client, fake_gateway, parse):
    gateway = fake_gateway(
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
def test_chat_parse_falls_back_after_two_failures(
    make_client, fake_gateway, parse, responses, reason
):
    gateway = fake_gateway(texts=responses)
    with make_client(gateway) as client:
        response = parse(client, "베어링 두 개 씀")

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] is None
    assert body["items"] == []
    assert body["ai"] == {"used": True, "fallback": True, "reason": reason}
    assert body["usage"]["success"] is False
    assert body["usage"]["attempts"] == 2


def test_chat_parse_times_out_within_budget(make_client, fake_gateway, parse):
    gateway = fake_gateway(texts=[1.0, 1.0])
    with make_client(gateway, chat_budget_seconds=0.05) as client:
        body = parse(client, "베어링 두 개 씀").json()

    assert body["ai"]["reason"] == "timeout"
    assert body["usage"]["latency_ms"] < 1000


def test_chat_parse_without_api_key_skips_llm(make_client, parse):
    with make_client() as client:
        body = parse(client, "베어링 두 개 씀").json()

    assert body["ai"] == {"used": False, "fallback": True, "reason": "error"}
    assert body["usage"] is None


def test_chat_parse_rejects_text_over_500(make_client, fake_gateway, parse):
    with make_client(fake_gateway()) as client:
        assert parse(client, "가" * 501).status_code == 422


def unit_vector(index):
    vector = [0.0] * EMBEDDING_DIM
    vector[index] = 2.0
    return vector


def test_embeddings_pass_task_and_normalize(make_client, fake_gateway, embed):
    gateway = fake_gateway(vectors=[[unit_vector(0), unit_vector(1)]])
    with make_client(gateway) as client:
        body = embed(client, ["육각볼트 M8-20", "헥사볼트 M8×20"]).json()

    texts, dim, task = gateway.embed_calls[0]
    assert texts == ["육각볼트 M8-20", "헥사볼트 M8×20"]
    assert (dim, task) == (EMBEDDING_DIM, EmbedTask.DOCUMENT)
    assert dim == 1024
    assert body["model"] == "fake-embedding"
    assert body["usage"]["model"] == "fake-embedding"
    assert len(body["vectors"]) == 2
    assert math.isclose(sum(v * v for v in body["vectors"][0]), 1.0)
    assert body["vectors"][0][0] == 1.0


@pytest.mark.parametrize(
    "bad",
    [
        [[0.0] * 768],
        [unit_vector(0), unit_vector(1)],
        [[0.0] * EMBEDDING_DIM],
    ],
    ids=["wrong_dim", "count_mismatch", "zero_vector"],
)
def test_embeddings_fall_back_on_bad_vectors(make_client, fake_gateway, embed, bad):
    gateway = fake_gateway(vectors=[bad, bad])
    with make_client(gateway) as client:
        body = embed(client, ["볼트"]).json()

    assert body["vectors"] is None
    assert body["model"] is None
    assert body["ai"] == {"used": True, "fallback": True, "reason": "schema_invalid"}


def test_embeddings_without_api_key_skips_llm(make_client, embed):
    with make_client() as client:
        body = embed(client, ["볼트"], task="query").json()

    assert body["ai"]["fallback"] is True
    assert body["usage"] is None


class WarmGateway:
    def __init__(self, error=None):
        self.warmed = 0
        self.error = error

    async def warm_up(self):
        self.warmed += 1
        if self.error:
            raise self.error


@pytest.mark.parametrize("error", [None, RuntimeError("bedrock down")])
def test_startup_warms_gateway_and_serves_even_if_warm_up_fails(make_client, error):
    gateway = WarmGateway(error)
    with make_client(gateway) as client:
        assert client.get("/health").json() == {"status": "ok", "llm": "ok"}
    assert gateway.warmed == 1


def test_warm_up_can_be_turned_off(make_client):
    gateway = WarmGateway()
    with make_client(gateway, warm_up=False) as client:
        client.get("/health")
    assert gateway.warmed == 0
