"""후속 질문 양식 답변 (F-REVIEW-09, REV-06).

MVP는 질문을 주제로 분류하고 같은 스냅샷의 숫자로 정해진 문장을 채운다. LLM 자유 답변은 확장.
분류되지 않거나 스냅샷에 없는 내용이면 "근거 데이터에 없습니다."
"""

from typing import Literal

from bjk_contracts import CheckCode
from pydantic import BaseModel, ConfigDict

from bjk_review.models import ReviewResult, ReviewSnapshot
from bjk_review.opinion import _day, _won

Topic = Literal["qty", "supplier", "price", "urgency", "risk"]
NO_EVIDENCE = "근거 데이터에 없습니다."

# 여러 주제에 걸리면 앞의 주제를 고른다. "얼마나 급해"는 단가(얼마)보다 긴급(급)이다.
TOPIC_KEYWORDS: tuple[tuple[Topic, tuple[str, ...]], ...] = (
    (
        "risk",
        (
            "위험",
            "리스크",
            "안 사면",
            "안사면",
            "안 시키면",
            "결품",
            "멈추",
            "손실",
            "환율",
            "운임",
        ),
    ),
    # "급" 한 글자는 "공급사"에도 걸리므로 쓰지 않는다
    ("urgency", ("급해", "급한", "급하", "급히", "긴급", "마감", "언제까지", "서둘", "빨리", "늦")),
    ("supplier", ("공급사", "업체", "거래처", "어디서", "어디에서")),
    ("price", ("단가", "가격", "비싸", "싸", "얼마", "금액")),
    ("qty", ("개", "수량", "몇", "많", "적", "줄", "늘")),
)


class Answer(BaseModel):
    """REV-06 응답."""

    model_config = ConfigDict(frozen=True)

    topic: Topic | None
    answer: str
    source: Literal["template"] = "template"
    evidence_refs: list[str]


def classify(question: str) -> Topic | None:
    text = question.replace(" ", "")
    for topic, words in TOPIC_KEYWORDS:
        if any(word.replace(" ", "") in text for word in words):
            return topic
    return None


def _check(result: ReviewResult, code: CheckCode):
    return next((c for c in result.checks if c.code == code), None)


def _stock_parts(s: ReviewSnapshot) -> tuple[list[str], list[str], int]:
    """현재 재고·입고 예정·확인된 숨은 재고·다른 요청을 문장 조각과 기호로."""
    parts = [f"현재 재고 {s.stock}개", f"입고 예정 {s.incoming}개"]
    refs = ["S", "O"]
    total = s.stock + s.incoming
    if s.hidden_confirmed:
        parts.append(f"확인된 숨은 재고 {s.hidden_confirmed}개")
        refs.append("H_c")
        total += s.hidden_confirmed
    if s.other_requests:
        parts.append(f"다른 요청 {s.other_requests}개")
        refs.append("P")
        total += s.other_requests
    return parts, refs, total


def _join(parts: list[str]) -> str:
    return ", ".join(parts[:-1]) + "와 " + parts[-1] if len(parts) > 1 else parts[0]


def answer_qty(result: ReviewResult, s: ReviewSnapshot) -> tuple[str, list[str]]:
    proposal = result.proposal
    parts, refs, total = _stock_parts(s)
    if proposal.no_order:
        text = (
            f"권장 발주량이 0개입니다. {_join(parts)}를 합친 {total}개가 "
            f"대비 기간 필요량(상위 95%) {s.d95}개보다 많기 때문입니다."
        )
        refs = ["R", *refs, "D95"]
    elif proposal.qty != result.original.qty:
        text = (
            f"권장 발주량은 {proposal.qty}개입니다. 대비 기간 필요량(상위 95%) {s.d95}개에서 "
            f"{_join(parts)}를 빼고 최소 주문 단위에 맞춘 값입니다."
        )
        refs = ["R", "D95", *refs, "MOQ"]
    else:
        text = f"요청 수량 {result.original.qty}개를 바꿀 근거가 없어 그대로 두었습니다."
        refs = ["Q"]
    if s.hidden_unconfirmed:
        text += f" 미확인 숨은 재고 {s.hidden_unconfirmed}개는 실사 전이라 빼지 않았습니다."
        refs.append("H_u")
    return text, refs


def answer_supplier(result: ReviewResult, s: ReviewSnapshot) -> tuple[str, list[str]]:
    proposal, original = result.proposal, result.original
    if proposal.no_order:
        return "이번 발주가 필요하지 않아 공급사를 고르지 않았습니다.", ["R"]
    if proposal.supplier_id != original.supplier_id:
        if CheckCode.C08 in proposal.basis:
            c08 = _check(result, CheckCode.C08).facts
            need = f" {_day(c08['t_need'])}" if c08.get("t_need") else ""
            return (
                f"요청 공급사 납기 {c08['LT90']}일로는 필요 시점{need}에 대기 어려워 "
                f"{proposal.supplier_name}로 바꿨습니다.",
                ["LT90", "t_need"],
            )
        return (
            f"요청 단가가 평소보다 높아 납기를 맞추는 공급사 중 배송비를 포함한 총액이 가장 낮은 "
            f"{proposal.supplier_name}로 바꿨습니다. 수정안 총액은 {_won(proposal.total)}입니다.",
            ["p_mean", "LT90"],
        )
    cheaper = next((a for a in result.alternatives if a.kind == "cheaper_supplier"), None)
    if cheaper is not None:
        return (
            f"공급사는 그대로입니다. {cheaper.supplier_name}가 {_won(cheaper.saving)} 더 싸지만 "
            f"요청 단가가 평소 범위라 대안으로만 보여드립니다.",
            ["p_mean"],
        )
    return f"공급사를 바꿀 근거가 없어 {original.supplier_name}를 유지했습니다.", []


def answer_price(result: ReviewResult, s: ReviewSnapshot) -> tuple[str, list[str]]:
    stats, price = s.price_stats, result.original.unit_price
    refs = ["p_mean", "sigma", "n"]
    if stats.n == 0 or stats.mean is None or price is None:
        return NO_EVIDENCE, []
    mean = _won(stats.mean)
    if _check(result, CheckCode.C05) is not None:
        return (
            f"요청 단가 {_won(price)}은 최근 {stats.n}건 평균 {mean}"
            f"(표준편차 {_won(stats.sigma)})보다 높습니다.",
            refs,
        )
    return f"요청 단가 {_won(price)}은 최근 {stats.n}건 평균 {mean}과 비교해 평소 범위입니다.", refs


def answer_urgency(result: ReviewResult, s: ReviewSnapshot) -> tuple[str, list[str]]:
    c08 = _check(result, CheckCode.C08)
    if c08 is not None:
        f = c08.facts
        if "deadline" in str(f.get("cause")) and f.get("deadline"):
            days = f["days_left"]
            deadline = _day(f["deadline"])
            if days < 0:
                return f"발주 마감일 {deadline}이 지나 긴급입니다.", ["t_deadline"]
            return f"발주 마감일 {deadline}까지 {days}일 남아 긴급입니다.", ["t_deadline"]
        return (
            f"요청 공급사 납기 {f['LT90']}일로는 필요 시점에 대기 어려워 긴급입니다.",
            ["LT90", "t_need"],
        )
    if s.t_deadline is not None:
        days = (s.t_deadline - s.as_of).days
        return (
            f"발주 마감일 {_day(s.t_deadline)}까지 {days}일 남아 긴급하지 않습니다.",
            ["t_deadline"],
        )
    return "8주 안에 재고가 바닥날 것으로 보이지 않아 긴급하지 않습니다.", ["t_out"]


def answer_risk(result: ReviewResult, s: ReviewSnapshot) -> tuple[str, list[str]]:
    risk = result.risk_if_not_ordered
    parts, refs = [], []
    if risk.stockout_date is not None:
        parts.append(f"발주하지 않으면 {_day(risk.stockout_date)}쯤 재고가 바닥납니다.")
        refs.append("t_out")
    if risk.equipment:
        parts.append(f"{', '.join(risk.equipment)} 설비가 멈출 수 있습니다.")
    if risk.loss:
        estimate = "(추정)" if risk.is_estimate else ""
        parts.append(f"예상 손실은 {_won(risk.loss)}{estimate}입니다.")
        refs.append("L")
    if s.import_dependent and s.r_lead >= 1:
        parts.append("해상운임 등 납기 위험이 주의 이상인 구간입니다.")
        refs.append("r_lead")
    if s.import_dependent and s.r_price >= 1:
        parts.append("환율 등 가격 위험이 주의 이상인 구간입니다.")
        refs.append("r_price")
    return (" ".join(parts), refs) if parts else (NO_EVIDENCE, [])


ANSWERS = {
    "qty": answer_qty,
    "supplier": answer_supplier,
    "price": answer_price,
    "urgency": answer_urgency,
    "risk": answer_risk,
}


def answer_question(question: str, result: ReviewResult, snapshot: ReviewSnapshot) -> Answer:
    """검토 결과와 그 스냅샷만 근거로 답한다. 보류 건은 근거 계산이 없다."""
    topic = classify(question)
    if topic is None or result.proposal is None:
        return Answer(topic=topic, answer=NO_EVIDENCE, evidence_refs=[])
    text, refs = ANSWERS[topic](result, snapshot)
    return Answer(topic=topic, answer=text, evidence_refs=refs if text != NO_EVIDENCE else [])
