"""의견서 표시 이름과 구성 형식 (API 명세서 2장 코드값, F-REVIEW-08).

ai가 쓴 의견서와 server의 양식 의견서가 같은 형식이어야 같은 검증을 통과한다. 그래서 둘 다
`render_opinion`으로 조립한다.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from bjk_contracts.opinion import CheckLevel, OpinionRequest

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
# 의견서의 체크 순서: 긴급 → 경고 → 정보
LEVEL_ORDER = {CheckLevel.URGENT: 0, CheckLevel.WARNING: 1, CheckLevel.INFO: 2}

PROPOSAL_LABEL = "수정안: "
RISK_LABEL = "미발주 시: "
ALTERNATIVES_LABEL = "대안: "
ESTIMATE_NOTE = "※ 사용 기록이 부족해 추정치 기반으로 계산했습니다."
FOOTER_LABEL = "계산 기준: "


def opinion_header(request: OpinionRequest) -> str:
    names = [VERDICT_NAMES[request.verdict], *(FLAG_NAMES[f] for f in request.flags)]
    return "[" + " · ".join(names) + "]"


def opinion_footer(computed_at: datetime) -> str:
    if computed_at.tzinfo is not None:
        computed_at = computed_at.astimezone(SEOUL)
    return f"{FOOTER_LABEL}{computed_at:%Y-%m-%d %H:%M}"


def render_opinion(
    request: OpinionRequest,
    *,
    summary: str,
    sentences: dict[str, str],
    proposal: str | None = None,
    risk: str | None = None,
    alternatives: str | None = None,
) -> str:
    """판정 머리 + 요약 → 체크별 문장(긴급 → 경고 → 정보) → 수정안 → 미발주 리스크 → 대안
    → (추정치 표시) → 계산 기준 시각. `sentences`는 걸린 체크 코드마다 한 문장.
    """
    lines = [f"{opinion_header(request)} {summary}"]
    ordered = sorted(request.checks, key=lambda c: LEVEL_ORDER[c.level])
    lines += [f"- {sentences[c.code]}" for c in ordered]
    if proposal and request.proposal is not None:
        lines.append(PROPOSAL_LABEL + proposal)
    if risk:
        lines.append(RISK_LABEL + risk)
    if alternatives and request.alternatives:
        lines.append(ALTERNATIVES_LABEL + alternatives)
    if request.data_mode == "estimated":
        lines.append(ESTIMATE_NOTE)
    lines.append(opinion_footer(request.computed_at))
    return "\n".join(lines)
