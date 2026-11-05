"""briefing 배치 (API 명세서 14장, 기능명세서 F-NOTI-02·F-APPROVAL-02). 매일 07:30.

1. 결정을 기다린 지 만료 시각이 지난 검토(`reviewed`·`held`)를 `expired`로 바꾸고 요청자에게 알린다.
2. 브리핑을 계산해 확인할 일이 있으면 사장님·관리자에게 알린다. 하루에 한 번만 만든다.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from bjk_server.auth import set_tenant
from bjk_server.briefing.service import DECISION_WAITING, briefing_title, build_briefing
from bjk_server.clock import KST
from bjk_server.db.models import Part, Review, User
from bjk_server.jobs.runner import company_ids, job
from bjk_server.notify.service import notify


def _expire_reviews(db, company_id, now: datetime) -> int:
    expired = db.scalars(
        select(Review).where(Review.status.in_(DECISION_WAITING), Review.expires_at <= now)
    ).all()
    for review in expired:
        review.status = "expired"
        review.updated_at = now
        if review.requested_by is None:
            continue
        part = db.get(Part, review.part_id) if review.part_id else None
        name = part.name if part else "요청한 부품"
        notify(
            db,
            company_id,
            [review.requested_by],
            "decision_result",
            f"{name} 발주 요청이 결정 없이 만료됐습니다.",
            now,
            channels=("chat",),
            target=("review", review.id),
            dedupe_key=f"review_expired:{review.id}",
        )
    return len(expired)


@job("briefing")
def run(session: Session, now: datetime) -> dict[str, Any]:
    today = now.astimezone(KST).date()
    expired = notified = 0
    for company_id in company_ids(session):
        set_tenant(session, company_id)
        expired += _expire_reviews(session, company_id, now)
        briefing = build_briefing(session, now)
        if not briefing["should_notify"]:
            continue
        managers = session.scalars(
            select(User.id).where(User.active, User.role.in_(("manager", "owner")))
        ).all()
        notified += len(
            notify(
                session,
                company_id,
                managers,
                "briefing",
                briefing_title(briefing),
                now,
                dedupe_key=f"briefing:{today.isoformat()}",
            )
        )
    return {"reviews_expired": expired, "notifications": notified}
