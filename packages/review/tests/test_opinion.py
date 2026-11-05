from uuid import UUID

import pytest
from bjk_contracts import AiMeta, FallbackReason, LlmPurpose, LlmUsage, OpinionResponse
from bjk_review import (
    OrderRequest,
    finalize_opinion,
    run_review,
    template_opinion,
    to_opinion_request,
    verify_opinion,
)

COMPANY_ID = UUID("6f1c2f9e-6d1a-4c3e-9a51-2b7f0c8d4e11")

# 실제 Gemini(gemini-3.5-flash-lite)가 V벨트 A-42 예시로 쓴 의견서 (2026-11-05 확인)
GEMINI_VBELT = """\
[수정 권고] 현재 재고와 입고 예정 물량이 충분하여 이번 발주는 불필요합니다.
- 현재 재고 2개와 입고 예정 10개가 있어 요청 수량 30개는 과다합니다.
- 요청 수량 30개는 월 소모량 1.5개 기준으로 20개월 치에 해당합니다.
- 11월 8일에 10개가 입고될 예정이므로 중복 발주입니다.
- 단가 18,000원은 최근 평균 단가 13,000원보다 높습니다.
- 공급사 B의 단가는 15,000원이며 납기는 8일입니다.
수정안: 이번 발주 불필요하며 총 540,000원을 절감합니다.
계산 기준: 2026-11-04 03:00"""


def opinion_request(snapshot, request):
    return to_opinion_request(run_review(snapshot, request), snapshot, company_id=COMPANY_ID)


@pytest.fixture
def vbelt_request(case):
    return opinion_request(*case("vbelt"))


def test_template_passes_verification_for_every_example(each_case):
    request = opinion_request(*each_case)

    assert verify_opinion(template_opinion(request), request) == []


def test_template_vbelt(vbelt_request):
    assert template_opinion(vbelt_request).splitlines() == [
        "[수정 권고] 이번 발주는 필요하지 않습니다.",
        "- 현재 재고 2개, 입고 예정 10개에 요청 30개를 더하면 "
        "넉넉한 필요량(상위 99%) 5개보다 많습니다.",
        "- 요청 30개는 월 소모량 1.5개 기준 20개월 치입니다.",
        "- 같은 부품 10개가 11월 8일 입고 예정입니다.",
        "- 요청 단가 18,000원은 최근 평균 13,000원보다 높습니다.",
        "- 공급사 B는 15,000원에, 납기 8일 안에 공급할 수 있습니다.",
        "수정안: 이번 발주 불필요, 540,000원 절감입니다.",
        "계산 기준: 2026-11-04 03:00",
    ]


def test_template_6205_shows_urgent_risk_and_estimate(case):
    text = template_opinion(opinion_request(*case("bearing_6205")))

    assert text.startswith("[적정 · 긴급] 요청대로 발주해도 됩니다.")
    assert "- 발주 마감일 11월 9일까지 5일 남았습니다." in text
    assert "미발주 시: 11월 20일쯤 재고가 바닥납니다. 3호기 설비가 멈출 수 있습니다." in text
    assert "예상 손실 2,400,000원(추정)." in text


def test_template_hold(case):
    snapshot, _ = case("vbelt")
    snapshot = snapshot.model_copy(update={"part_id": None})
    request = opinion_request(snapshot, OrderRequest(qty=30))
    text = template_opinion(request)

    assert text.startswith("[보류] 확인이 필요한 정보가 있어 검토를 멈췄습니다")
    assert "(부품을 확정하지 못함)" in text.splitlines()[0]
    assert verify_opinion(text, request) == []


def test_real_gemini_opinion_passes(vbelt_request):
    assert verify_opinion(GEMINI_VBELT, vbelt_request) == []


@pytest.mark.parametrize(
    ("before", "after", "error"),
    [
        ("총 540,000원을", "총 46만 5천 원을", "허용 목록에 없는 숫자: 46만 5천(465,000)"),
        ("20개월", "18개월", "허용 목록에 없는 숫자: 18"),
        ("평균 단가 13,000원", "평균 단가 13,500원", "허용 목록에 없는 숫자: 13,500"),
        ("11월 8일에", "11월 9일에", "허용 목록에 없는 날짜: 11월 9일"),
        ("높습니다.", "45% 높습니다.", "허용 목록에 없는 비율: 45%"),
        ("[수정 권고]", "[적정]", "첫 줄 판정 표시가 [수정 권고]와 다름"),
        ("발주는 불필요합니다.", "발주는 불필요합니다. [적정]", "본문에 판정 표시 [적정]가 섞임"),
        ("03:00", "04:00", "허용 목록에 없는 시각: 04:00"),
    ],
)
def test_verification_catches_wrong_content(vbelt_request, before, after, error):
    text = GEMINI_VBELT.replace(before, after, 1)

    assert error in verify_opinion(text, vbelt_request)


def test_verification_catches_missing_check(vbelt_request):
    text = GEMINI_VBELT.replace("- 단가 18,000원은 최근 평균 단가 13,000원보다 높습니다.\n", "")
    errors = verify_opinion(text, vbelt_request)

    assert "체크 근거 줄이 5개여야 하는데 4개" in errors


def test_verification_allows_rounding_and_korean_units(vbelt_request):
    text = GEMINI_VBELT.replace("총 540,000원을", "총 54만 원을").replace(
        "높습니다.", "약 38% 높습니다."
    )
    assert verify_opinion(text, vbelt_request) == []


def test_verification_ignores_digits_in_names(case):
    request = opinion_request(*case("bearing_6205"))
    text = template_opinion(request).replace("요청대로", "볼베어링 6205ZZ는 요청대로")

    assert verify_opinion(text, request) == []


def response(text, *, fallback=False):
    usage = LlmUsage(
        purpose=LlmPurpose.OPINION,
        model="m",
        input_tokens=1,
        output_tokens=1,
        latency_ms=1,
        attempts=1,
        success=not fallback,
    )
    if fallback:
        return OpinionResponse(text=None, ai=AiMeta.failed(FallbackReason.TIMEOUT), usage=usage)
    return OpinionResponse(text=text, ai=AiMeta.ok(), usage=usage)


class Writer:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        return self.responses.pop(0)


def test_finalize_uses_verified_llm_text(vbelt_request):
    writer = Writer(response(GEMINI_VBELT))
    opinion = finalize_opinion(vbelt_request, writer)

    assert (opinion.source, opinion.verified, opinion.attempts) == ("llm", True, 1)
    assert opinion.text == GEMINI_VBELT
    assert len(opinion.usages) == 1


def test_finalize_rewrites_with_feedback(vbelt_request):
    wrong = GEMINI_VBELT.replace("총 540,000원을", "총 46만 5천 원을")
    writer = Writer(response(wrong), response(GEMINI_VBELT))
    opinion = finalize_opinion(vbelt_request, writer)

    assert (opinion.source, opinion.attempts) == ("llm", 2)
    retry = writer.requests[1]
    assert retry.previous_text == wrong
    assert retry.feedback == ["허용 목록에 없는 숫자: 46만 5천(465,000)"]


def test_finalize_falls_back_to_template_after_two_rewrites(vbelt_request):
    wrong = GEMINI_VBELT.replace("20개월", "18개월")
    writer = Writer(response(wrong), response(wrong), response(wrong))
    opinion = finalize_opinion(vbelt_request, writer)

    assert len(writer.requests) == 3
    assert (opinion.source, opinion.verified) == ("template", True)
    assert opinion.text == template_opinion(vbelt_request)
    assert len(opinion.feedback) == 3


@pytest.mark.parametrize("result", [None, "fallback"])
def test_finalize_uses_template_when_ai_unavailable(vbelt_request, result):
    writer = Writer(None if result is None else response(None, fallback=True))
    opinion = finalize_opinion(vbelt_request, writer)

    assert (opinion.source, opinion.verified, opinion.attempts) == ("template", True, 1)
