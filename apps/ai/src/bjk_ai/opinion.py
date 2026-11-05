"""발주 검토 의견서 문장 (F-REVIEW-08).

LLM은 문장만 쓴다. 판정 표시(첫 줄 머리)와 계산 기준 시각(마지막 줄)은 입력값으로 코드가 붙이고,
구성 순서도 코드가 맞춘다. 걸린 체크가 빠지거나 없는 체크가 섞이면 다시 쓰게 한다.
"""

import json
from zoneinfo import ZoneInfo

from bjk_contracts import (
    AiMeta,
    CheckLevel,
    FallbackReason,
    LlmPurpose,
    OpinionRequest,
    OpinionResponse,
)
from pydantic import BaseModel

from bjk_ai.config import Settings
from bjk_ai.gateway import AttemptFailed, CallLog, LlmGateway, call_with_retry, usage_from

SEOUL = ZoneInfo("Asia/Seoul")

VERDICT_NAMES = {"ok": "적정", "revise": "수정 권고", "hold": "보류"}
FLAG_NAMES = {"urgent": "긴급", "caution": "주의", "alternative": "대안"}
LEVEL_NAMES = {"urgent": "긴급", "warning": "경고", "info": "정보"}
CHECK_NAMES = {
    "C-01": "수량 과다",
    "C-02": "장기 재고화",
    "C-03": "중복 발주",
    "C-04": "숨은 재고",
    "C-05": "단가 이상",
    "C-06": "더 싼 공급사",
    "C-07": "수량 부족",
    "C-08": "마감 임박",
    "C-09": "외부 리스크",
}
HOLD_REASON_NAMES = {
    "part_unresolved": "부품을 확정하지 못함",
    "supplier_unresolved": "공급사를 특정하지 못하고 기본 공급사도 없음",
    "no_demand_data": "사용 기록·정비 일정·사용 추정치가 모두 없음",
}
# 의견서의 체크 순서: 긴급 → 경고 → 정보 (F-REVIEW-08)
LEVEL_ORDER = {CheckLevel.URGENT: 0, CheckLevel.WARNING: 1, CheckLevel.INFO: 2}

SYSTEM_PROMPT = """\
너는 영세 제조 공장 사장님께 올리는 발주 검토 의견서의 문장을 쓴다.
판정·수정안·숫자는 이미 계산이 끝났다. 너는 주어진 값을 쉬운 한국어 문장으로 옮기기만 한다.

반드시 지킬 것:
- 입력에 있는 숫자만 쓴다. 새로 계산하거나(합, 차, 비율, 개월 수 등) 반올림하거나 추정하지 않는다.
- 금액은 "540,000원", 수량은 "10개", 날짜는 "11월 8일"처럼 쓴다.
- 판정을 바꾸거나 다르게 해석하지 않는다.
- 판정 단어([수정 권고] 등)는 쓰지 않는다. 머리는 따로 붙는다.
- 입력에 없는 사실(뉴스, 시세, 공급사 사정 등)을 덧붙이지 않는다.
- 존댓말로, 한 문장은 짧게 쓴다.

출력 필드:
- summary: 판정의 이유를 한 문장으로 요약
- checks: 입력의 체크마다 정확히 하나씩, code와 근거 문장. 입력에 없는 체크는 쓰지 않는다.
- proposal: 수정안과 금액을 한두 문장으로. 입력에 수정안이 없으면 null
  ("이번 발주 불필요"면 그렇게 쓰고 절감액을 적는다.
   saving이 음수면 추가 비용과 피하는 예상 손실을 적는다)
- risk: 발주하지 않을 때의 위험(소진 예상일, 멈추는 설비, 예상 손실)을 한 문장으로.
  위험 정보가 없으면 null
- alternatives: 대안의 금액 비교를 한 문장으로. 입력에 대안이 없으면 null

주의 표시(caution)가 있고 숨은 재고 체크에 미확인 재고(H_u)가 있으면,
그 재고의 실사 확인을 권하는 말을 해당 체크 문장에 넣는다.

근거 숫자 기호:
Q 요청 수량, S 현재 재고, O 입고 예정, H_c 확인된 숨은 재고, H_u 미확인 숨은 재고(실사 필요),
P 같은 부품의 다른 열린 요청 수량, m 월 소모량, F 확정 필요량(정비), F_12m 향후 12개월 확정 필요량,
D95·D99 대비 기간 필요량(상위 95%·99%), R 권장 발주량, MOQ 최소 주문 수량,
p_mean 최근 평균 단가, sigma 단가 표준편차, n 최근 구매 건수, LT90 늦을 때 납기(일),
months 몇 개월 치인지, incoming_qty 입고 예정 수량, eta 입고 예정일, deadline 발주 마감일
"""


class _LlmCheckSentence(BaseModel):
    code: str
    sentence: str


class _LlmOpinion(BaseModel):
    summary: str
    checks: list[_LlmCheckSentence]
    proposal: str | None = None
    risk: str | None = None
    alternatives: str | None = None


def build_prompt(request: OpinionRequest) -> str:
    payload = request.model_dump(mode="json", exclude={"company_id", "previous_text", "feedback"})
    payload["verdict_name"] = VERDICT_NAMES[request.verdict]
    payload["flag_names"] = [FLAG_NAMES[f] for f in request.flags]
    payload["hold_reason_names"] = [HOLD_REASON_NAMES[r] for r in request.hold_reasons]
    for check in payload["checks"]:
        check["name"] = CHECK_NAMES[check["code"]]
        check["level_name"] = LEVEL_NAMES[check["level"]]
    prompt = "검토 결과(JSON):\n" + json.dumps(payload, ensure_ascii=False, indent=2)
    if request.feedback:
        prompt += (
            "\n\n이전에 쓴 의견서가 검증에서 틀렸다. 아래 항목을 고쳐 다시 써라.\n"
            f"이전 의견서:\n{request.previous_text}\n틀린 항목:\n"
            + "\n".join(f"- {item}" for item in request.feedback)
        )
    return prompt


def header(request: OpinionRequest) -> str:
    names = [VERDICT_NAMES[request.verdict], *(FLAG_NAMES[f] for f in request.flags)]
    return "[" + " · ".join(names) + "]"


def footer(request: OpinionRequest) -> str:
    computed_at = request.computed_at
    if computed_at.tzinfo is not None:
        computed_at = computed_at.astimezone(SEOUL)
    return f"계산 기준: {computed_at:%Y-%m-%d %H:%M}"


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def assemble(request: OpinionRequest, output: _LlmOpinion) -> str:
    """LLM 문장을 F-REVIEW-08 순서로 묶는다. 체크가 빠지거나 남으면 `AttemptFailed`."""
    summary = _clean(output.summary)
    sentences: dict[str, str] = {}
    for item in output.checks:
        sentence = _clean(item.sentence)
        if item.code in sentences or sentence is None:
            raise AttemptFailed(FallbackReason.SCHEMA_INVALID)
        sentences[item.code] = sentence
    if summary is None or set(sentences) != {c.code for c in request.checks}:
        raise AttemptFailed(FallbackReason.SCHEMA_INVALID)

    lines = [f"{header(request)} {summary}"]
    ordered = sorted(request.checks, key=lambda c: LEVEL_ORDER[c.level])
    lines += [f"- {sentences[c.code]}" for c in ordered]
    proposal = _clean(output.proposal) if request.proposal is not None else None
    if proposal:
        lines.append(f"수정안: {proposal}")
    if risk := _clean(output.risk):
        lines.append(f"미발주 시: {risk}")
    alternatives = _clean(output.alternatives) if request.alternatives else None
    if alternatives:
        lines.append(f"대안: {alternatives}")
    if request.data_mode == "estimated":
        lines.append("※ 사용 기록이 부족해 추정치 기반으로 계산했습니다.")
    lines.append(footer(request))
    return "\n".join(lines)


async def write_opinion(
    request: OpinionRequest, *, gateway: LlmGateway | None, settings: Settings
) -> OpinionResponse:
    if gateway is None:
        return OpinionResponse(
            text=None, ai=AiMeta(used=False, fallback=True, reason=FallbackReason.ERROR)
        )

    model = settings.gemini_opinion_model
    prompt = build_prompt(request)

    async def attempt(log: CallLog) -> str:
        result = await gateway.generate_json(
            model=model, system=SYSTEM_PROMPT, prompt=prompt, schema=_LlmOpinion
        )
        log.input_tokens += result.input_tokens
        log.output_tokens += result.output_tokens
        return assemble(request, _LlmOpinion.model_validate_json(result.text))

    text, reason, log = await call_with_retry(
        attempt, budget_seconds=settings.opinion_budget_seconds
    )
    usage = usage_from(log, purpose=LlmPurpose.OPINION, model=model, success=text is not None)
    if text is None:
        return OpinionResponse(text=None, ai=AiMeta.failed(reason), usage=usage)
    return OpinionResponse(text=text, ai=AiMeta.ok(), usage=usage)
