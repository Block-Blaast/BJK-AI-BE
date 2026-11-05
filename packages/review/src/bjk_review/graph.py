"""발주 검토 처리 단계 (F-REVIEW-01) LangGraph 그래프.

    interpret → snapshot → hold_check ─┬→ checks → proposal → verdict → opinion → verify → 끝
                                       └──────(보류)──────────→ verdict      ↑         │
                                                                             └─(재작성)─┘

- 규칙 노드(snapshot 이후 opinion 전까지, verify)는 순수 함수만 쓴다. LLM 노드는 opinion 하나다.
- 노드 이름은 SSE `review.progress` 단계 이름과 같다. 노드를 지날 때마다 그 이름을 내보내고,
  끝나면 `done`을 내보낸다.
- DB 조회(근거 고정), ai 호출(의견서), 요청 해석은 server가 `ReviewDeps`로 넣는다.
- 검증에 실패하면 틀린 항목을 담아 opinion으로 되돌아간다(최대 2회). 그래도 틀리거나 ai가 응답하지
  않으면 양식 의견서로 끝낸다.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, TypedDict
from uuid import UUID

from bjk_contracts import HoldReason, LlmUsage, OpinionRequest, OpinionResponse
from langgraph.graph import END, START, StateGraph

from bjk_review.checks import Context, run_checks
from bjk_review.engine import (
    build_alternatives,
    build_proposal,
    decide,
    hold_reasons,
    hold_result,
    make_context,
    original_line,
)
from bjk_review.models import (
    AlternativeLine,
    Check,
    OrderRequest,
    ProposalLine,
    ReviewResult,
    ReviewSettings,
    ReviewSnapshot,
)
from bjk_review.opinion import MAX_REWRITES, Opinion, template_opinion, to_opinion_request
from bjk_review.verify import verify_opinion

Entry = Literal["staff_request", "stock_draft", "missed_draft"]

# SSE `review.progress` 단계 (API 명세서 11장). 앞의 8개가 그래프 노드 이름이다.
PROGRESS_STEPS = (
    "interpret",
    "snapshot",
    "hold_check",
    "checks",
    "proposal",
    "verdict",
    "opinion",
    "verify",
    "done",
)


@dataclass(frozen=True)
class Interpreted:
    """요청 해석 결과. 부품을 확정하지 못하면 `part_id`가 None이고 검토는 보류된다."""

    part_id: str | None
    order: OrderRequest


@dataclass(frozen=True)
class ReviewDeps:
    """server가 넣는 함수들. 예외를 던지지 않는다(실패는 None)."""

    # 근거 고정: 부품·원안에 맞는 스냅샷을 DB에서 모아 고정한다(F-REVIEW-02)
    load_snapshot: Callable[[str | None, OrderRequest], ReviewSnapshot]
    # 의견서 문장: ai `/v1/opinions` 호출. 실패면 None
    write_opinion: Callable[[OpinionRequest], OpinionResponse | None]
    # 직원 요청 원문 해석: ai 채팅 해석 + 매칭 + 공급사 표현 해석. 원안을 이미 받았으면 쓰지 않음
    interpret: Callable[[str], Interpreted | None] | None = None


class ReviewState(TypedDict, total=False):
    # 입력
    company_id: UUID
    entry: Entry
    text: str | None
    part_id: str | None
    order: OrderRequest | None
    settings: ReviewSettings
    # 단계별 결과
    snapshot: ReviewSnapshot
    hold: list[HoldReason]
    ctx: Context
    checks: list[Check]
    proposal: ProposalLine
    alternatives: list[AlternativeLine]
    result: ReviewResult
    opinion_request: OpinionRequest
    draft: str | None
    feedback: list[list[str]]
    attempts: int
    usages: list[LlmUsage]
    opinion: Opinion


@dataclass(frozen=True)
class ReviewOutcome:
    """검토 한 건의 결과. server는 이것을 `review_requests`에 저장한다(REV-02)."""

    snapshot: ReviewSnapshot
    result: ReviewResult
    opinion: Opinion


def build_review_graph(deps: ReviewDeps):
    def interpret(state: ReviewState) -> ReviewState:
        # 시스템 초안과 확인 카드를 거친 직원 요청은 원안이 이미 있다(F-REVIEW-01 0단계 생략)
        if state.get("order") is not None:
            return {}
        found = deps.interpret(state["text"]) if deps.interpret and state.get("text") else None
        if found is None:
            return {"part_id": None, "order": OrderRequest(qty=0)}
        return {"part_id": found.part_id, "order": found.order}

    def snapshot(state: ReviewState) -> ReviewState:
        return {"snapshot": deps.load_snapshot(state.get("part_id"), state["order"])}

    def hold_check(state: ReviewState) -> ReviewState:
        return {"hold": hold_reasons(state["snapshot"], state["order"])}

    def checks(state: ReviewState) -> ReviewState:
        ctx = make_context(state["snapshot"], state["order"], state["settings"])
        return {"ctx": ctx, "checks": run_checks(ctx)}

    def proposal(state: ReviewState) -> ReviewState:
        ctx = state["ctx"]
        line = build_proposal(ctx, state["checks"], original_line(ctx))
        return {"proposal": line, "alternatives": build_alternatives(ctx, state["checks"], line)}

    def verdict(state: ReviewState) -> ReviewState:
        if state["hold"]:
            result = hold_result(
                state["snapshot"], state["order"], state["settings"], state["hold"]
            )
        else:
            result = decide(
                state["ctx"],
                state["order"],
                state["checks"],
                state["proposal"],
                state["alternatives"],
            )
        request = to_opinion_request(result, state["snapshot"], company_id=state["company_id"])
        return {
            "result": result,
            "opinion_request": request,
            "feedback": [],
            "attempts": 0,
            "usages": [],
        }

    def opinion(state: ReviewState) -> ReviewState:
        request = state["opinion_request"]
        if state["feedback"]:
            request = request.model_copy(
                update={"previous_text": state["draft"], "feedback": state["feedback"][-1]}
            )
        try:
            response = deps.write_opinion(request)
        except Exception:
            # ai 호출이 예외를 던져도 검토는 양식 의견서로 끝나야 한다(설계 원칙 7)
            response = None
        usages = list(state["usages"])
        if response is not None and response.usage is not None:
            usages.append(response.usage)
        return {
            "draft": response.text if response is not None else None,
            "attempts": state["attempts"] + 1,
            "usages": usages,
        }

    def verify(state: ReviewState) -> ReviewState:
        request, draft = state["opinion_request"], state["draft"]
        common = {"attempts": state["attempts"], "usages": state["usages"]}
        if draft is not None:
            errors = verify_opinion(draft, request)
            if not errors:
                return {
                    "opinion": Opinion(
                        text=draft,
                        source="llm",
                        verified=True,
                        feedback=state["feedback"],
                        **common,
                    )
                }
            feedback = [*state["feedback"], errors]
            if state["attempts"] <= MAX_REWRITES:
                return {"feedback": feedback}  # opinion으로 되돌아가 다시 쓴다
        else:
            feedback = state["feedback"]
        text = template_opinion(request)
        return {
            "feedback": feedback,
            "opinion": Opinion(
                text=text,
                source="template",
                verified=not verify_opinion(text, request),
                feedback=feedback,
                **common,
            ),
        }

    graph = StateGraph(ReviewState)
    for name, node in (
        ("interpret", interpret),
        ("snapshot", snapshot),
        ("hold_check", hold_check),
        ("checks", checks),
        ("proposal", proposal),
        ("verdict", verdict),
        ("opinion", opinion),
        ("verify", verify),
    ):
        graph.add_node(name, node)
    graph.add_edge(START, "interpret")
    graph.add_edge("interpret", "snapshot")
    graph.add_edge("snapshot", "hold_check")
    graph.add_conditional_edges(
        "hold_check", lambda s: "verdict" if s["hold"] else "checks", ["verdict", "checks"]
    )
    graph.add_edge("checks", "proposal")
    graph.add_edge("proposal", "verdict")
    graph.add_edge("verdict", "opinion")
    graph.add_edge("opinion", "verify")
    graph.add_conditional_edges(
        "verify", lambda s: END if s.get("opinion") is not None else "opinion", [END, "opinion"]
    )
    return graph.compile()


def run_review_flow(
    deps: ReviewDeps,
    *,
    company_id: UUID,
    entry: Entry,
    order: OrderRequest | None = None,
    part_id: str | None = None,
    text: str | None = None,
    settings: ReviewSettings | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> ReviewOutcome:
    """검토 한 건을 끝까지 돌린다. `on_progress`로 SSE `review.progress` 단계를 받는다.

    시스템 초안(`stock_draft`, `missed_draft`)과 확인 카드를 거친 직원 요청은 `order`·`part_id`를
    넘긴다. 원문만 있는 직원 요청은 `text`를 넘기고 `deps.interpret`가 해석한다.
    """
    graph = build_review_graph(deps)
    state: ReviewState = {
        "company_id": company_id,
        "entry": entry,
        "text": text,
        "part_id": part_id,
        "order": order,
        "settings": settings or ReviewSettings(),
    }
    final: ReviewState = state
    for mode, chunk in graph.stream(state, stream_mode=["updates", "values"]):
        if mode == "updates" and on_progress is not None:
            for step in chunk:
                on_progress(step)
        elif mode == "values":
            final = chunk
    if on_progress is not None:
        on_progress("done")
    return ReviewOutcome(
        snapshot=final["snapshot"], result=final["result"], opinion=final["opinion"]
    )
