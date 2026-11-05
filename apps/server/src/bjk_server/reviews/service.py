"""검토 생성·실행·저장 (F-REVIEW-01, API 명세서 REV-02, NOT-03).

검토는 `reviewing`으로 만들고 커밋한 뒤 엔진(`bjk_review.run_review_flow`)을 돌린다. 근거 수집,
진행 단계 이벤트, 결과 저장은 각각 짧은 트랜잭션이라 의견서를 기다리는 동안 DB를 잡지 않고,
화면은 `review.progress`를 단계마다 바로 받는다. ai가 없거나 실패해도 양식 의견서로 끝난다.
"""

import logging
import uuid
from collections.abc import Callable
from concurrent.futures import Executor, ThreadPoolExecutor
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Annotated, Any

from bjk_contracts import OpinionRequest, OpinionResponse
from bjk_review import OrderRequest, ReviewDeps, ReviewOutcome, ReviewSettings, run_review_flow
from bjk_review.graph import Entry
from fastapi import Depends
from sqlalchemy import event
from sqlalchemy.orm import Session

from bjk_server import clock
from bjk_server.ai.client import AiClient, AiUnavailable, get_ai_client
from bjk_server.ai.usage import record_usage
from bjk_server.auth import set_tenant
from bjk_server.db.models import CompanySettings, Review, ReviewSnapshot
from bjk_server.db.session import get_session_scope
from bjk_server.defaults import default_settings
from bjk_server.events import publish
from bjk_server.reviews.snapshot import collect_snapshot

logger = logging.getLogger(__name__)

SessionScope = Callable[[], AbstractContextManager[Session]]
Clock = Callable[[], datetime]


def company_settings(db: Session, company_id: uuid.UUID) -> dict[str, dict[str, Any]]:
    row = db.get(CompanySettings, company_id)
    return {"review": row.review, "system": row.system} if row else default_settings()


def review_settings(settings: dict[str, dict[str, Any]]) -> ReviewSettings:
    """회사 설정(SYS-01)의 검토 기준값 (docs/ai-integration.md 5-2)."""
    review, system = settings["review"], settings["system"]
    return ReviewSettings(
        c02_months=review["c02_months"],
        c05_sigma=review["c05_sigma"],
        c06_ratio=review["c06_ratio"],
        c08_days=review["c08_days"],
        c05_min_ratio=system["c05_min_ratio"],
        c05_small_n_ratio=system["c05_small_n_ratio"],
    )


def create_review(
    db: Session,
    company_id: uuid.UUID,
    *,
    entry: Entry,
    order: OrderRequest,
    part_id: uuid.UUID | None,
    requested_by: uuid.UUID | None = None,
    source_message_id: uuid.UUID | None = None,
    text: str | None = None,
) -> Review:
    """`reviewing` 검토를 만들고 `review.created`를 같은 트랜잭션에 남긴다. 실행은 커밋 뒤."""
    review = Review(
        id=uuid.uuid4(),
        company_id=company_id,
        entry=entry,
        status="reviewing",
        part_id=part_id,
        requested_by=requested_by,
        source_message_id=source_message_id,
        request={**order.model_dump(mode="json"), "text": text},
    )
    db.add(review)
    db.flush()
    publish(db, company_id, "review.created", {"review_id": str(review.id), "entry": entry})
    return review


def _opinion_writer(ai: AiClient | None) -> Callable[[OpinionRequest], OpinionResponse | None]:
    def write(request: OpinionRequest) -> OpinionResponse | None:
        if ai is None:
            return None
        try:
            return ai.write_opinion(request)
        except AiUnavailable:
            return None

    return write


def _progress(review_id: uuid.UUID, step: str, at: datetime) -> dict:
    return {"review_id": str(review_id), "step": step, "at": at.astimezone(clock.KST).isoformat()}


def _save(db: Session, review: Review, outcome: ReviewOutcome, settings: dict, now: datetime):
    result, opinion, snapshot = outcome.result, outcome.opinion, outcome.snapshot
    held = result.verdict == "hold"
    review.status = "held" if held else "reviewed"
    review.verdict = result.verdict
    review.flags = list(result.flags)
    review.hold_reasons = list(result.hold_reasons)
    if snapshot.part_id is not None:
        review.part_id = uuid.UUID(snapshot.part_id)
    review.result = result.model_dump(
        mode="json", exclude={"verdict", "flags", "hold_reasons", "review_hash"}
    )
    review.opinion = {"text": opinion.text, "source": opinion.source, "verified": opinion.verified}
    review.original_total = result.original.total
    review.saving = result.proposal.saving if result.proposal else 0
    review.loss = result.risk_if_not_ordered.loss
    # 보류는 보완을, 검토완료는 결정을 기다린다. 둘 다 이 기간이 지나면 만료 (F-APPROVAL-02)
    review.expires_at = now + timedelta(days=settings["system"]["review_expire_days"])
    review.updated_at = now
    db.add(
        ReviewSnapshot(
            company_id=review.company_id,
            review_id=review.id,
            hash=result.review_hash,
            values=snapshot.model_dump(mode="json"),
            settings=review_settings(settings).model_dump(mode="json"),
            computed_at=snapshot.computed_at,
        )
    )
    for usage in opinion.usages:
        record_usage(db, review.company_id, usage)


def run_review(
    scope: SessionScope,
    ai: AiClient | None,
    company_id: uuid.UUID,
    review_id: uuid.UUID,
    now: Clock = clock.utcnow,
) -> str | None:
    """커밋된 `reviewing` 검토 하나를 끝까지 돌려 저장한다. 바뀐 상태를 돌려준다.

    이미 다른 상태면 아무것도 하지 않고 None. 결과 저장과 `done` 단계 이벤트는 한 트랜잭션이다.
    """
    with scope() as db:
        set_tenant(db, company_id)
        review = db.get(Review, review_id)
        if review is None or review.status != "reviewing":
            return None
        settings = company_settings(db, company_id)
        order = OrderRequest.model_validate(review.request)
        part_id = str(review.part_id) if review.part_id else None
        entry = review.entry

    def load_snapshot(part: str | None, order: OrderRequest):
        with scope() as db:
            set_tenant(db, company_id)
            return collect_snapshot(
                db, part, order, now=now(), settings=settings, review_id=review_id
            )

    def on_progress(step: str) -> None:
        if step == "done":
            return  # 결과를 저장한 뒤 같은 트랜잭션에서 보낸다
        with scope() as db:
            set_tenant(db, company_id)
            publish(db, company_id, "review.progress", _progress(review_id, step, now()))

    outcome = run_review_flow(
        ReviewDeps(load_snapshot=load_snapshot, write_opinion=_opinion_writer(ai)),
        company_id=company_id,
        entry=entry,
        order=order,
        part_id=part_id,
        settings=review_settings(settings),
        on_progress=on_progress,
    )
    with scope() as db:
        set_tenant(db, company_id)
        review = db.get(Review, review_id, with_for_update=True)
        if review is None or review.status != "reviewing":
            return None
        finished = now()
        _save(db, review, outcome, settings, finished)
        publish(db, company_id, "review.progress", _progress(review_id, "done", finished))
        return review.status


@dataclass
class ReviewRunner:
    """요청 트랜잭션이 커밋된 뒤 검토를 백그라운드에서 돌린다.

    커밋 전에 돌리면 다른 세션에서 검토 행이 보이지 않으므로 세션의 after_commit에 건다.
    롤백되면 돌리지 않는다.
    """

    scope: SessionScope
    ai: AiClient | None
    executor: Executor

    def start_after_commit(self, db: Session, company_id: uuid.UUID, review_id: uuid.UUID):
        def submit(_session: Session) -> None:
            self.executor.submit(self._run, company_id, review_id)

        event.listen(db, "after_commit", submit, once=True)

    def _run(self, company_id: uuid.UUID, review_id: uuid.UUID) -> None:
        try:
            run_review(self.scope, self.ai, company_id, review_id)
        except Exception:
            # 실패한 검토는 reviewing으로 남는다. 다음 요청을 막지 않도록 기록만 한다.
            logger.exception("검토 실행 실패 review_id=%s", review_id)


_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="review")


def get_review_runner(
    scope: Annotated[SessionScope, Depends(get_session_scope)],
    ai: Annotated[AiClient | None, Depends(get_ai_client)],
) -> ReviewRunner:
    return ReviewRunner(scope, ai, _executor)
