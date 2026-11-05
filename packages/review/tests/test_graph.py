from uuid import UUID

import pytest
from bjk_contracts import AiMeta, OpinionResponse
from bjk_review import (
    PROGRESS_STEPS,
    Interpreted,
    OrderRequest,
    ReviewDeps,
    build_review_graph,
    finalize_opinion,
    run_review,
    run_review_flow,
    template_opinion,
    to_opinion_request,
)

COMPANY_ID = UUID("6f1c2f9e-6d1a-4c3e-9a51-2b7f0c8d4e11")
ALL_STEPS = list(PROGRESS_STEPS)


class Writer:
    """ai `/v1/opinions` 대신. 받은 요청을 기록하고 정해 둔 문장을 차례로 돌려준다.

    "good"은 검증을 통과하는 문장(양식 의견서와 같은 내용), "bad"는 허용 목록에 없는 숫자를 넣은
    문장, None은 ai 무응답이다.
    """

    def __init__(self, *plan):
        self.plan = list(plan)
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        kind = self.plan.pop(0)
        if kind is None:
            return None
        if kind == "raise":
            raise RuntimeError("ai down")
        base = request.model_copy(update={"previous_text": None, "feedback": []})
        text = template_opinion(base)
        if kind == "bad":
            text = text.replace("계산 기준", "총 46만 5천 원 절감\n계산 기준")
        return OpinionResponse(text=text, ai=AiMeta.ok())


def run(case_snapshot, order, writer, **kwargs):
    steps = []
    loaded = []

    def load_snapshot(part_id, request):
        loaded.append((part_id, request))
        return case_snapshot

    deps = ReviewDeps(load_snapshot=load_snapshot, write_opinion=writer, **kwargs.pop("deps", {}))
    outcome = run_review_flow(
        deps,
        company_id=COMPANY_ID,
        entry=kwargs.pop("entry", "staff_request"),
        order=order,
        part_id=kwargs.pop("part_id", "p-1"),
        on_progress=steps.append,
        **kwargs,
    )
    return outcome, steps, loaded


def test_graph_nodes_match_progress_steps():
    graph = build_review_graph(ReviewDeps(load_snapshot=None, write_opinion=None))
    nodes = [n for n in graph.get_graph().nodes if not n.startswith("__")]

    assert nodes == ALL_STEPS[:-1]


def test_flow_matches_engine_and_emits_every_step(each_case):
    snapshot, order = each_case
    outcome, steps, _ = run(snapshot, order, Writer("good"))

    assert outcome.result == run_review(snapshot, order)
    assert steps == ALL_STEPS
    assert (outcome.opinion.source, outcome.opinion.verified, outcome.opinion.attempts) == (
        "llm",
        True,
        1,
    )


def test_flow_opinion_matches_finalize_opinion(case):
    snapshot, order = case("vbelt")
    outcome, _, _ = run(snapshot, order, Writer("bad", "good"))
    request = to_opinion_request(run_review(snapshot, order), snapshot, company_id=COMPANY_ID)
    direct = finalize_opinion(request, Writer("bad", "good"))

    assert outcome.opinion.text == direct.text
    assert outcome.opinion.feedback == direct.feedback
    assert outcome.opinion.attempts == direct.attempts == 2


def test_verify_failure_loops_back_to_opinion_with_feedback(case):
    snapshot, order = case("vbelt")
    writer = Writer("bad", "good")
    outcome, steps, _ = run(snapshot, order, writer)

    assert steps == [*ALL_STEPS[:-1], "opinion", "verify", "done"]
    retry = writer.requests[1]
    assert retry.previous_text is not None
    assert retry.feedback == ["허용 목록에 없는 숫자: 46만 5천(465,000)"]
    assert outcome.opinion.source == "llm"


def test_two_failed_rewrites_end_with_template(case):
    snapshot, order = case("vbelt")
    writer = Writer("bad", "bad", "bad")
    outcome, steps, _ = run(snapshot, order, writer)

    assert len(writer.requests) == 3
    assert steps.count("opinion") == 3
    assert (outcome.opinion.source, outcome.opinion.verified) == ("template", True)
    assert len(outcome.opinion.feedback) == 3


@pytest.mark.parametrize("kind", [None, "raise"])
def test_ai_unavailable_ends_with_template(case, kind):
    snapshot, order = case("vbelt")
    outcome, steps, _ = run(snapshot, order, Writer(kind))

    assert steps == ALL_STEPS
    assert outcome.opinion.source == "template"
    assert outcome.result.verdict == "revise"


def test_hold_skips_checks_and_proposal(case):
    snapshot, _ = case("vbelt")
    snapshot = snapshot.model_copy(update={"part_id": None})
    outcome, steps, _ = run(snapshot, OrderRequest(qty=30), Writer("good"), part_id=None)

    assert steps == ["interpret", "snapshot", "hold_check", "verdict", "opinion", "verify", "done"]
    assert outcome.result.verdict == "hold"
    assert outcome.opinion.text.startswith("[보류]")


def test_system_draft_skips_interpretation(case):
    snapshot, order = case("bearing_6205")
    interpret_calls = []
    outcome, _, loaded = run(
        snapshot,
        order,
        Writer("good"),
        entry="stock_draft",
        deps={"interpret": interpret_calls.append},
    )

    assert interpret_calls == []
    assert loaded == [("p-1", order)]
    assert outcome.result.flags == ["urgent"]


def test_staff_request_text_is_interpreted(case):
    snapshot, _ = case("vbelt")
    parsed = OrderRequest(qty=30, supplier_id="sup-a", unit_price=18000)

    def interpret(text):
        assert text == "V벨트 30개 시켜주세요, 저번 데서요"
        return Interpreted(part_id="p-42", order=parsed)

    outcome, _, loaded = run(
        snapshot,
        None,
        Writer("good"),
        part_id=None,
        text="V벨트 30개 시켜주세요, 저번 데서요",
        deps={"interpret": interpret},
    )

    assert loaded == [("p-42", parsed)]
    assert outcome.result.proposal.saving == 540000


def test_uninterpretable_request_is_held(case):
    snapshot, _ = case("vbelt")
    held = snapshot.model_copy(update={"part_id": None})
    outcome, _, loaded = run(
        held, None, Writer("good"), part_id=None, text="그거 좀", deps={"interpret": lambda t: None}
    )

    assert loaded == [(None, OrderRequest(qty=0))]
    assert outcome.result.verdict == "hold"
