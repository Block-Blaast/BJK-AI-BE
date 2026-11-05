"""놓친 발주 스캔 (기능명세서 F-MISSED-01). 매일 07:00.

아무도 올리지 않았지만 지금 발주해야 하는 부품을 찾아 시스템 초안(`missed_draft`)을 만들고 직원
요청과 같은 검토를 거친다. 초안은 작업 트랜잭션과 함께 커밋되고, 검토는 커밋 직후 차례로 돈다.
"""

import uuid
from collections.abc import Callable
from concurrent.futures import Executor, Future
from datetime import date, datetime, timedelta
from typing import Any

from bjk_review import OrderRequest
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session, sessionmaker

from bjk_server.ai.client import get_ai_client
from bjk_server.auth import set_tenant
from bjk_server.clock import KST
from bjk_server.db.models import Part, Review
from bjk_server.inventory import latest_metrics_subquery
from bjk_server.jobs.runner import company_ids, job
from bjk_server.reviews.service import ReviewRunner, company_settings, create_review
from bjk_server.reviews.snapshot import OPEN_REVIEW_STATUSES

# 초안을 막는 부품을 고르는 함수들. 열린 발주(F-APPROVAL-02)는 발주 테이블이 생기면 더한다.
Blocker = Callable[[Session, date], set[uuid.UUID]]


def _open_reviews(db: Session, today: date) -> set[uuid.UUID]:
    """열린 요청·초안(검토중·검토완료·보류)이 있는 부품."""
    return set(
        db.scalars(
            select(Review.part_id).where(
                Review.part_id.is_not(None), Review.status.in_(OPEN_REVIEW_STATUSES)
            )
        )
    )


def _closed_no_order_today(db: Session, today: date) -> set[uuid.UUID]:
    """오늘 '발주 불필요'로 닫힌 검토가 있는 부품. 다음 새벽 계산 전까지 다시 만들지 않는다."""
    return set(
        db.scalars(
            select(Review.part_id).where(
                Review.part_id.is_not(None),
                Review.status == "closed",
                Review.decision["action"].astext == "accept_no_order",
                func.date(func.timezone("Asia/Seoul", Review.decided_at)) == today,
            )
        )
    )


BLOCKERS: tuple[Blocker, ...] = (_open_reviews, _closed_no_order_today)


def missed_parts(db: Session, today: date, settings: dict[str, dict[str, Any]]) -> list[Any]:
    """대상 부품의 최신 지표를 우선순위(P_out × L) 높은 순으로. 권장 발주량이 0이면 뺀다."""
    metrics = latest_metrics_subquery()
    rows = db.execute(
        select(metrics)
        .join(Part, and_(Part.id == metrics.c.part_id, Part.merged_into.is_(None)))
        .where(
            metrics.c.p_out >= settings["system"]["missed_p_out_min"],
            metrics.c.t_deadline <= today + timedelta(days=settings["review"]["c08_days"]),
            metrics.c.recommended_qty > 0,
        )
        .order_by(metrics.c.priority.desc(), metrics.c.part_id)
    ).all()
    blocked = set().union(*(block(db, today) for block in BLOCKERS))
    return [row for row in rows if row.part_id not in blocked]


class _Inline(Executor):
    """배치 안에서는 검토를 순서대로 끝까지 돌린다."""

    def submit(self, fn, /, *args, **kwargs) -> Future:
        future: Future = Future()
        future.set_result(fn(*args, **kwargs))
        return future


@job("missed-scan")
def missed_scan(session: Session, now: datetime) -> dict[str, Any]:
    today = now.astimezone(KST).date()
    scope = sessionmaker(session.get_bind(), expire_on_commit=False).begin
    runner = ReviewRunner(scope, get_ai_client(), _Inline())
    companies = company_ids(session)
    drafts = 0
    for cid in companies:
        set_tenant(session, cid)
        for row in missed_parts(session, today, company_settings(session, cid)):
            supplier = str(row.default_supplier_id) if row.default_supplier_id else None
            review = create_review(
                session,
                cid,
                entry="missed_draft",
                order=OrderRequest(qty=row.recommended_qty, supplier_id=supplier),
                part_id=row.part_id,
            )
            runner.start_after_commit(session, cid, review.id)
            drafts += 1
    return {"companies": len(companies), "drafts_created": drafts}
