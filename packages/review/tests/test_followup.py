from datetime import date, datetime, timedelta

import pytest
from bjk_review import (
    OrderRequest,
    answer_question,
    classify,
    decision_changed,
    needs_refresh,
    recheck,
    run_review,
)


def reviewed(case, name):
    snapshot, request = case(name)
    return run_review(snapshot, request), snapshot


def ask(case, name, question):
    result, snapshot = reviewed(case, name)
    return answer_question(question, result, snapshot)


# 재검토 ----------------------------------------------------------------------------------


def test_recheck_with_edited_qty_matches_rev04_example(case):
    snapshot, _ = case("vbelt")
    result = recheck(snapshot, OrderRequest(qty=6, supplier_id="sup-a", unit_price=18000))

    assert result.verdict == "revise"
    assert result.checks[0].facts == {"S": 2, "O": 10, "H_c": 0, "Q": 6, "D99": 5, "MOQ": 1}
    assert result.proposal.qty == 0
    assert (
        result.review_hash
        == recheck(snapshot, OrderRequest(qty=6, supplier_id="sup-a", unit_price=18000)).review_hash
    )


def test_recheck_hash_differs_by_edited_values(case):
    snapshot, _ = case("vbelt")
    a = recheck(snapshot, OrderRequest(qty=6, supplier_id="sup-a", unit_price=18000))
    b = recheck(snapshot, OrderRequest(qty=7, supplier_id="sup-a", unit_price=18000))

    assert a.review_hash != b.review_hash


@pytest.mark.parametrize(
    ("hours", "moved", "expected"),
    [(23, False, False), (25, False, True), (1, True, True)],
)
def test_needs_refresh(case, hours, moved, expected):
    snapshot, _ = case("vbelt")
    now = snapshot.computed_at + timedelta(hours=hours)

    assert needs_refresh(snapshot, now=now, part_moved_since=moved) is expected


def test_decision_changed_when_new_stock_arrives(case):
    snapshot, request = case("bolt_unconfirmed")
    before = run_review(snapshot, request)
    refreshed = snapshot.model_copy(
        update={"stock": 200, "computed_at": datetime.fromisoformat("2026-11-05T03:00:00+09:00")}
    )
    after = run_review(refreshed, request)

    assert decision_changed(before, after) is True
    assert decision_changed(before, run_review(snapshot, request)) is False


# 후속 질문 -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("question", "topic"),
    [
        ("왜 0개야?", "qty"),
        ("몇 개 사야 돼?", "qty"),
        ("공급사 왜 바꿨어?", "supplier"),
        ("왜 이렇게 비싸?", "price"),
        ("얼마나 급해?", "urgency"),
        ("공급사 급하게 바꿔야 해?", "urgency"),
        ("공급사 어디야?", "supplier"),
        ("안 사면 어떻게 돼?", "risk"),
        ("점심 뭐 먹지", None),
    ],
)
def test_classify(question, topic):
    assert classify(question) == topic


def test_why_zero_matches_rev06_example(case):
    answer = ask(case, "vbelt", "왜 0개야?")

    assert answer.topic == "qty"
    assert answer.answer == (
        "권장 발주량이 0개입니다. 현재 재고 2개와 입고 예정 10개를 합친 12개가 "
        "대비 기간 필요량(상위 95%) 4개보다 많기 때문입니다."
    )
    assert answer.source == "template"
    assert answer.evidence_refs == ["R", "S", "O", "D95"]


def test_qty_answer_mentions_unconfirmed_hidden_stock(case):
    answer = ask(case, "bolt_unconfirmed", "왜 80개로 늘렸어?")

    assert answer.answer.startswith(
        "권장 발주량은 80개입니다. 대비 기간 필요량(상위 95%) 120개에서"
    )
    assert "미확인 숨은 재고 800개는 실사 전이라 빼지 않았습니다." in answer.answer
    assert "H_u" in answer.evidence_refs


def test_supplier_switch_by_price(case):
    answer = ask(case, "bearing_6204", "공급사 왜 바꿨어?")

    assert "공급사 B로 바꿨습니다" in answer.answer
    assert "148,000원" in answer.answer


def test_supplier_kept_with_alternative(case):
    answer = ask(case, "bearing_6203", "공급사 C가 더 싸지 않아?")

    assert answer.topic == "supplier"
    assert answer.answer.startswith("공급사는 그대로입니다. 공급사 C가 11,000원 더 싸지만")


def test_price_anomaly_answer(case):
    answer = ask(case, "vbelt", "단가가 왜 문제야?")

    assert (
        answer.answer
        == "요청 단가 18,000원은 최근 4건 평균 13,000원(표준편차 1,200원)보다 높습니다."
    )


def test_urgency_answers(case):
    assert (
        ask(case, "bearing_6205", "급해?").answer == "발주 마감일 11월 9일까지 5일 남아 긴급입니다."
    )
    assert ask(case, "vbelt", "급해?").answer == (
        "8주 안에 재고가 바닥날 것으로 보이지 않아 긴급하지 않습니다."
    )


def test_risk_answer(case):
    answer = ask(case, "bearing_6205", "안 사면 어떻게 돼?")

    assert answer.answer == (
        "발주하지 않으면 11월 20일쯤 재고가 바닥납니다. 3호기 설비가 멈출 수 있습니다. "
        "예상 손실은 2,400,000원(추정)입니다. 해상운임 등 납기 위험이 주의 이상인 구간입니다."
    )


def test_no_evidence(case):
    assert ask(case, "vbelt", "안 사면 어떻게 돼?").answer == "근거 데이터에 없습니다."
    assert ask(case, "bolt_confirmed", "단가 괜찮아?").answer == "근거 데이터에 없습니다."
    unknown = ask(case, "vbelt", "점심 뭐 먹지")
    assert (unknown.topic, unknown.answer, unknown.evidence_refs) == (
        None,
        "근거 데이터에 없습니다.",
        [],
    )


def test_hold_has_no_evidence(case):
    snapshot, _ = case("vbelt")
    snapshot = snapshot.model_copy(update={"part_id": None})
    result = run_review(snapshot, OrderRequest(qty=30))

    assert answer_question("왜 0개야?", result, snapshot).answer == "근거 데이터에 없습니다."


def test_past_deadline_is_urgent(case):
    snapshot, request = case("bearing_6205")
    snapshot = snapshot.model_copy(update={"t_deadline": date(2026, 11, 2)})
    result = run_review(snapshot, request)

    assert (
        answer_question("급해?", result, snapshot).answer
        == "발주 마감일 11월 2일이 지나 긴급입니다."
    )
