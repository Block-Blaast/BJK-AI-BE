import json

import pytest

CATEGORIES = [
    {"id": "cat-bearing", "name": "베어링"},
    {"id": "cat-bolt", "name": "볼트·너트"},
]


@pytest.fixture
def suggest(company_id):
    def _suggest(client, names):
        rows = [{"row": i + 2, "name": name} for i, name in enumerate(names)]
        body = {"company_id": company_id, "categories": CATEGORIES, "rows": rows}
        return client.post("/v1/imports/suggest", json=body)

    return _suggest


def llm_rows(*rows):
    return json.dumps({"rows": list(rows)}, ensure_ascii=False)


def bolt_row(row=2, **overrides):
    item = {
        "row": row,
        "spec": [{"key": "thread", "value": "m8"}, {"key": "length_mm", "value": " 20 "}],
        "category_id": "cat-bolt",
        "confidence": 0.93,
    }
    return {**item, **overrides}


def test_suggest_normalizes_spec_and_keeps_registered_category(make_client, fake_gateway, suggest):
    gateway = fake_gateway(texts=[llm_rows(bolt_row())])
    with make_client(gateway) as client:
        body = suggest(client, ["육각볼트 M8-20"]).json()

    assert body["suggestions"] == [
        {
            "row": 2,
            "spec": {"thread": "M8", "length_mm": "20"},
            "category_id": "cat-bolt",
            "confidence": 0.93,
        }
    ]
    assert body["ai"]["fallback"] is False
    prompt = json.loads(gateway.generate_calls[0])
    assert prompt["categories"] == CATEGORIES
    assert prompt["rows"] == [{"row": 2, "name": "육각볼트 M8-20"}]


def test_unregistered_category_is_dropped(make_client, fake_gateway, suggest):
    gateway = fake_gateway(texts=[llm_rows(bolt_row(category_id="cat-oil", confidence=0.9))])
    with make_client(gateway) as client:
        [row] = suggest(client, ["수용성 절삭유 20L"]).json()["suggestions"]

    assert (row["category_id"], row["confidence"]) == (None, 0.0)


def test_unknown_spec_key_is_schema_invalid(make_client, fake_gateway, suggest):
    bad = bolt_row(spec=[{"key": "color", "value": "red"}])
    gateway = fake_gateway(texts=[llm_rows(bad), llm_rows(bad)])
    with make_client(gateway) as client:
        body = suggest(client, ["육각볼트 M8-20"]).json()

    assert body["suggestions"] is None
    assert body["ai"]["reason"] == "schema_invalid"


def test_missing_row_retries(make_client, fake_gateway, suggest):
    gateway = fake_gateway(
        texts=[
            llm_rows(bolt_row(2)),
            llm_rows(bolt_row(2), bolt_row(3, category_id=None, confidence=0)),
        ]
    )
    with make_client(gateway) as client:
        body = suggest(client, ["육각볼트 M8-20", "이름 모를 부품"]).json()

    assert [s["row"] for s in body["suggestions"]] == [2, 3]
    assert body["usage"]["attempts"] == 2


def test_rows_are_split_into_chunks_and_merged_in_order(make_client, fake_gateway, suggest):
    names = [f"육각볼트 M8-{i}" for i in range(60)]
    first = llm_rows(*(bolt_row(i + 2) for i in range(50)))
    second = llm_rows(*(bolt_row(i + 2) for i in range(50, 60)))
    gateway = fake_gateway(texts=[first, second])
    with make_client(gateway) as client:
        body = suggest(client, names).json()

    assert len(gateway.generate_calls) == 2
    assert [s["row"] for s in body["suggestions"]] == list(range(2, 62))
    assert body["usage"]["input_tokens"] == 20


def test_one_failed_chunk_falls_back_entirely(make_client, fake_gateway, suggest):
    names = [f"육각볼트 M8-{i}" for i in range(60)]
    first = llm_rows(*(bolt_row(i + 2) for i in range(50)))
    gateway = fake_gateway(texts=[first, RuntimeError("down"), RuntimeError("down")])
    with make_client(gateway) as client:
        body = suggest(client, names).json()

    assert body["suggestions"] is None
    assert body["ai"] == {"used": True, "fallback": True, "reason": "error"}


def test_without_api_key_falls_back(make_client, suggest):
    with make_client() as client:
        body = suggest(client, ["육각볼트 M8-20"]).json()

    assert body["suggestions"] is None
    assert body["ai"]["used"] is False


def test_duplicate_rows_rejected(make_client, fake_gateway, company_id):
    rows = [{"row": 2, "name": "a"}, {"row": 2, "name": "b"}]
    with make_client(fake_gateway()) as client:
        response = client.post(
            "/v1/imports/suggest",
            json={"company_id": company_id, "categories": CATEGORIES, "rows": rows},
        )

    assert response.status_code == 422
