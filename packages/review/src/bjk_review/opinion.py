"""의견서: 검토 결과 → 의견서 요청, 양식 의견서, 작성·검증·재작성 흐름 (F-REVIEW-08).

LLM 문장은 ai(`/v1/opinions`)가 쓰고, 검증과 양식 대체는 여기서 한다. ai가 멈춰도 양식 의견서로
검토가 끝난다.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Literal
from uuid import UUID

from bjk_contracts import (
    Alternative,
    CheckFacts,
    LlmUsage,
    OpinionRequest,
    OpinionResponse,
    OrderLine,
    Proposal,
    Risk,
)
from bjk_contracts.opinion_format import HOLD_REASON_NAMES, render_opinion

from bjk_review.models import ReviewResult, ReviewSnapshot
from bjk_review.verify import verify_opinion

MAX_REWRITES = 2


def to_opinion_request(
    result: ReviewResult, snapshot: ReviewSnapshot, *, company_id: UUID
) -> OpinionRequest:
    """LLM에는 판정, 걸린 체크의 근거 숫자, 수정안, 리스크, 대안만 넘긴다."""
    original = result.original
    proposal = result.proposal
    return OpinionRequest(
        company_id=company_id,
        part_name=snapshot.part_name or "부품 미확정",
        verdict=result.verdict,
        flags=result.flags,
        hold_reasons=result.hold_reasons,
        checks=[CheckFacts(code=c.code, level=c.level, facts=c.facts) for c in result.checks],
        original=OrderLine(
            qty=original.qty,
            supplier_name=original.supplier_name,
            unit_price=original.unit_price,
            total=original.total,
        ),
        proposal=None
        if proposal is None
        else Proposal(
            qty=proposal.qty,
            supplier_name=proposal.supplier_name,
            unit_price=proposal.unit_price,
            total=proposal.total,
            saving=proposal.saving,
            no_order=proposal.no_order,
            basis=proposal.basis,
        ),
        alternatives=[
            Alternative(
                kind=a.kind,
                supplier_name=a.supplier_name,
                qty=a.qty,
                unit_price=a.unit_price,
                total=a.total,
                saving=a.saving,
            )
            for a in result.alternatives
        ],
        risk_if_not_ordered=Risk(
            stockout_date=result.risk_if_not_ordered.stockout_date,
            equipment=result.risk_if_not_ordered.equipment,
            loss=result.risk_if_not_ordered.loss,
            is_estimate=result.risk_if_not_ordered.is_estimate,
        ),
        data_mode=snapshot.data_mode,
        computed_at=snapshot.computed_at,
    )


def _won(value: int | float) -> str:
    return f"{int(value):,}원"


def _day(value: str | date | None) -> str:
    if value is None:
        return ""
    day = date.fromisoformat(value) if isinstance(value, str) else value
    return f"{day.month}월 {day.day}일"


def _check_sentence(code: str, facts: dict) -> str:
    f = facts
    match code:
        case "C-01":
            hidden = f", 확인된 숨은 재고 {f['H_c']}개" if f.get("H_c") else ""
            return (
                f"현재 재고 {f['S']}개, 입고 예정 {f['O']}개{hidden}에 요청 {f['Q']}개를 더하면 "
                f"넉넉한 필요량(상위 99%) {f['D99']}개보다 많습니다."
            )
        case "C-02":
            if f.get("months") is None:
                return f"최근 사용 기록과 정비 수요가 없어 요청 {f['Q']}개가 오래 쌓일 수 있습니다."
            return f"요청 {f['Q']}개는 월 소모량 {f['m']}개 기준 {f['months']}개월 치입니다."
        case "C-03":
            parts = []
            if f.get("incoming_qty"):
                when = f" {_day(f['eta'])}" if f.get("eta") else ""
                parts.append(f"같은 부품 {f['incoming_qty']}개가{when} 입고 예정입니다.")
            if f.get("open_request_qty"):
                parts.append(f"같은 부품의 다른 요청 {f['open_request_qty']}개가 진행 중입니다.")
            return " ".join(parts) or "같은 부품의 열린 발주가 있습니다."
        case "C-04":
            text = (
                f"같은 규격으로 다른 이름에 등록된 재고가 있습니다"
                f"(확인 {f['H_c']}개, 미확인 {f['H_u']}개)."
            )
            if f.get("H_u"):
                text += " 미확인 재고는 실사로 확인해 주세요."
            return text
        case "C-05":
            price, mean = _won(f["unit_price"]), _won(f["p_mean"])
            return f"요청 단가 {price}은 최근 평균 {mean}보다 높습니다."
        case "C-06":
            price = _won(f["unit_price"])
            return f"{f['supplier']}는 {price}에, 납기 {f['LT90']}일 안에 공급할 수 있습니다."
        case "C-07":
            return f"요청을 더해도 대비 기간 필요량(상위 95%) {f['D95']}개에 못 미칩니다."
        case "C-08":
            parts = []
            causes = str(f.get("cause", "")).split(",")
            if "deadline" in causes and f.get("deadline"):
                days = f.get("days_left", 0)
                if days < 0:
                    parts.append(f"발주 마감일 {_day(f['deadline'])}이 지났습니다.")
                else:
                    parts.append(f"발주 마감일 {_day(f['deadline'])}까지 {days}일 남았습니다.")
            if "supplier_lead" in causes:
                need = f" {_day(f['t_need'])}까지" if f.get("t_need") else ""
                parts.append(f"요청 공급사 납기 {f['LT90']}일로는{need} 받기 어렵습니다.")
            return " ".join(parts) or "지금 발주해도 일정이 빠듯합니다."
        case "C-09":
            parts = []
            if (f.get("r_lead") or 0) >= 1:
                parts.append("해상운임 등 납기 위험이 높은 구간입니다.")
            if (f.get("r_price") or 0) >= 1:
                parts.append("환율 상승 구간입니다.")
            if f.get("holiday"):
                parts.append(f"납기 기간에 {f['holiday']} 연휴가 겹칩니다.")
            return " ".join(parts) or "외부 요인을 확인해 주세요."
    raise ValueError(code)


def template_opinion(request: OpinionRequest) -> str:
    """LLM 없이 쓰는 정해진 양식 의견서. 입력값만 쓰므로 검증을 항상 통과해야 한다."""
    proposal = request.proposal
    if request.verdict == "hold":
        reasons = ", ".join(HOLD_REASON_NAMES[r] for r in request.hold_reasons)
        summary = f"확인이 필요한 정보가 있어 검토를 멈췄습니다({reasons})."
    elif proposal is not None and proposal.no_order:
        summary = "이번 발주는 필요하지 않습니다."
    elif request.verdict == "revise":
        summary = "수정안으로 발주하는 것을 권합니다."
    else:
        summary = "요청대로 발주해도 됩니다."

    proposal_text = None
    if proposal is not None and request.verdict == "revise":
        if proposal.no_order:
            proposal_text = f"이번 발주 불필요, {_won(proposal.saving)} 절감입니다."
        else:
            proposal_text = (
                f"{proposal.supplier_name} {proposal.qty}개, 단가 {_won(proposal.unit_price)}, "
                f"총 {_won(proposal.total)}"
            )
            if proposal.saving > 0:
                proposal_text += f", {_won(proposal.saving)} 절감입니다."
            elif proposal.saving < 0:
                proposal_text += f", 추가 비용 {_won(-proposal.saving)}"
                loss = request.risk_if_not_ordered.loss
                proposal_text += f"(피하는 예상 손실 {_won(loss)})입니다." if loss else "입니다."
            else:
                proposal_text += "입니다."

    risk = request.risk_if_not_ordered
    risk_parts = []
    if risk.stockout_date is not None:
        risk_parts.append(f"{_day(risk.stockout_date)}쯤 재고가 바닥납니다.")
    if risk.equipment:
        risk_parts.append(f"{', '.join(risk.equipment)} 설비가 멈출 수 있습니다.")
    if risk.loss:
        estimate = "(추정)" if risk.is_estimate else ""
        risk_parts.append(f"예상 손실 {_won(risk.loss)}{estimate}.")

    alternatives = []
    for a in request.alternatives:
        if a.kind == "cheaper_supplier":
            alternatives.append(
                f"{a.supplier_name} {a.qty}개 총 {_won(a.total)}({_won(a.saving)} 저렴)"
            )
        else:
            alternatives.append(f"{a.qty}개로 늘리면 단가 {_won(a.unit_price)}, 총 {_won(a.total)}")

    return render_opinion(
        request,
        summary=summary,
        sentences={c.code: _check_sentence(c.code, c.facts) for c in request.checks},
        proposal=proposal_text,
        risk=" ".join(risk_parts) or None,
        alternatives="; ".join(alternatives) or None,
    )


@dataclass
class Opinion:
    """REV-02 `opinion`과 같은 내용. `usages`는 server가 `llm_calls`에 저장한다."""

    text: str
    source: Literal["llm", "template"]
    verified: bool
    attempts: int = 0
    feedback: list[list[str]] = field(default_factory=list)
    usages: list[LlmUsage] = field(default_factory=list)


def finalize_opinion(
    request: OpinionRequest, write: Callable[[OpinionRequest], OpinionResponse | None]
) -> Opinion:
    """ai로 쓰고 검증한다. 틀리면 틀린 항목을 알려 최대 2번 다시 쓰고, 그래도 틀리거나
    ai가 대체 응답(또는 None)을 주면 양식 의견서로 바꾼다.

    `write`는 server의 ai 호출. 예외를 던지지 말고 실패면 None을 돌려준다.
    """
    opinion = Opinion(text="", source="template", verified=False)
    current = request
    while opinion.attempts <= MAX_REWRITES:
        opinion.attempts += 1
        response = write(current)
        if response is not None and response.usage is not None:
            opinion.usages.append(response.usage)
        if response is None or response.text is None:
            break
        errors = verify_opinion(response.text, request)
        if not errors:
            opinion.text, opinion.source, opinion.verified = response.text, "llm", True
            return opinion
        opinion.feedback.append(errors)
        current = request.model_copy(update={"previous_text": response.text, "feedback": errors})

    opinion.text = template_opinion(request)
    opinion.verified = not verify_opinion(opinion.text, request)
    return opinion
