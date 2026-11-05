import json

import pytest


@pytest.fixture
def vbelt_review(company_id):
    """F-REVIEW-10 V벨트 A-42 예시 (REV-02 응답과 같은 값)."""
    return {
        "company_id": company_id,
        "part_name": "V벨트 A-42",
        "verdict": "revise",
        "flags": [],
        "checks": [
            {
                "code": "C-06",
                "level": "info",
                "facts": {"supplier": "공급사 B", "unit_price": 15000},
            },
            {"code": "C-01", "level": "warning", "facts": {"S": 2, "O": 10, "Q": 30, "D99": 5}},
            {
                "code": "C-03",
                "level": "warning",
                "facts": {"incoming_qty": 10, "eta": "2026-11-08"},
            },
        ],
        "original": {"qty": 30, "supplier_name": "공급사 A", "unit_price": 18000, "total": 540000},
        "proposal": {
            "qty": 0,
            "total": 0,
            "saving": 540000,
            "no_order": True,
            "basis": ["C-01", "C-03"],
        },
        "computed_at": "2026-11-04T03:00:00+09:00",
    }


def llm_opinion(codes, **fields):
    body = {
        "summary": "이번 발주는 필요하지 않습니다.",
        "checks": [{"code": code, "sentence": f"{code} 근거입니다."} for code in codes],
        "proposal": "이번 발주 불필요, 540,000원 절감입니다.",
        "risk": None,
        "alternatives": None,
    }
    body.update(fields)
    return json.dumps(body, ensure_ascii=False)


def write(client, review):
    return client.post("/v1/opinions", json=review)


def test_opinion_assembles_fixed_order(make_client, fake_gateway, vbelt_review):
    gateway = fake_gateway(texts=[llm_opinion(["C-06", "C-01", "C-03"])])
    with make_client(gateway) as client:
        body = write(client, vbelt_review).json()

    assert body["ai"] == {"used": True, "fallback": False, "reason": None}
    assert body["text"].splitlines() == [
        "[수정 권고] 이번 발주는 필요하지 않습니다.",
        "- C-01 근거입니다.",
        "- C-03 근거입니다.",
        "- C-06 근거입니다.",
        "수정안: 이번 발주 불필요, 540,000원 절감입니다.",
        "계산 기준: 2026-11-04 03:00",
    ]
    prompt = gateway.generate_calls[0]
    assert '"verdict_name": "수정 권고"' in prompt
    assert '"name": "중복 발주"' in prompt
    assert vbelt_review["company_id"] not in prompt


def test_opinion_header_has_flags_and_estimate_note(make_client, fake_gateway, vbelt_review):
    review = {
        **vbelt_review,
        "verdict": "ok",
        "flags": ["urgent", "alternative"],
        "checks": [{"code": "C-08", "level": "urgent", "facts": {"deadline": "2026-11-09"}}],
        "proposal": None,
        "alternatives": [
            {
                "kind": "cheaper_supplier",
                "supplier_name": "공급사 C",
                "qty": 10,
                "unit_price": 7900,
                "total": 79000,
                "saving": 11000,
            }
        ],
        "data_mode": "estimated",
        "computed_at": "2026-11-03T18:00:00+00:00",
    }
    gateway = fake_gateway(
        texts=[
            llm_opinion(
                ["C-08"], proposal="무시될 문장", alternatives="공급사 C가 11,000원 쌉니다."
            )
        ]
    )
    with make_client(gateway) as client:
        lines = write(client, review).json()["text"].splitlines()

    assert lines[0].startswith("[적정 · 긴급 · 대안] ")
    assert "수정안: 무시될 문장" not in lines
    assert "대안: 공급사 C가 11,000원 쌉니다." in lines
    assert lines[-2] == "※ 사용 기록이 부족해 추정치 기반으로 계산했습니다."
    assert lines[-1] == "계산 기준: 2026-11-04 03:00"


def test_opinion_retries_when_a_check_is_missing(make_client, fake_gateway, vbelt_review):
    gateway = fake_gateway(
        texts=[llm_opinion(["C-01", "C-03"]), llm_opinion(["C-01", "C-03", "C-06"])]
    )
    with make_client(gateway) as client:
        body = write(client, vbelt_review).json()

    assert body["ai"]["fallback"] is False
    assert body["usage"]["attempts"] == 2


@pytest.mark.parametrize(
    "codes",
    [["C-01", "C-03"], ["C-01", "C-03", "C-06", "C-09"], ["C-01", "C-01", "C-03", "C-06"]],
    ids=["missing", "extra", "duplicate"],
)
def test_opinion_falls_back_when_checks_do_not_match(
    make_client, fake_gateway, vbelt_review, codes
):
    gateway = fake_gateway(texts=[llm_opinion(codes), llm_opinion(codes)])
    with make_client(gateway) as client:
        body = write(client, vbelt_review).json()

    assert body["text"] is None
    assert body["ai"] == {"used": True, "fallback": True, "reason": "schema_invalid"}


def test_opinion_rewrite_includes_feedback(make_client, fake_gateway, vbelt_review):
    review = {
        **vbelt_review,
        "previous_text": "[수정 권고] 이번 발주는 필요하지 않습니다. 46만 원 절감",
        "feedback": ["허용 목록에 없는 숫자: 460000"],
    }
    gateway = fake_gateway(texts=[llm_opinion(["C-01", "C-03", "C-06"])])
    with make_client(gateway) as client:
        write(client, review)

    prompt = gateway.generate_calls[0]
    assert "46만 원 절감" in prompt
    assert "- 허용 목록에 없는 숫자: 460000" in prompt


def test_opinion_feedback_requires_previous_text(make_client, fake_gateway, vbelt_review):
    with make_client(fake_gateway()) as client:
        response = write(client, {**vbelt_review, "feedback": ["틀림"]})

    assert response.status_code == 422


def test_opinion_without_api_key_falls_back(make_client, vbelt_review):
    with make_client() as client:
        body = write(client, vbelt_review).json()

    assert body == {
        "text": None,
        "ai": {"used": False, "fallback": True, "reason": "error"},
        "usage": None,
    }
