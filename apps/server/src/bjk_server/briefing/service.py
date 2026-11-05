"""아침 브리핑 (API 명세서 DSH-01, 기능명세서 F-NOTI-02, F-MISSED-02, F-SETUP-04).

브리핑은 저장하지 않고 조회할 때 계산한다. 다섯 건수가 모두 0이면 알리지 않는다.
- 놓친 발주: 결정을 기다리는 놓친 발주 초안(`missed_draft`), 예상 손실이 큰 순
- 검토 대기: 결정을 기다리는 직원 요청·재고 부족 초안(`reviewed`·`held`)
- 실사 필요: 아직 실사를 요청하지 않은 열린 의심 항목
- 주문 확인 필요: 승인하고 24시간이 지나도록 주문 완료 표시가 없는 발주
- 정비 완료 확인 필요: 예정일 + 2일이 지나도록 완료 기록이 없는 정비
"""

from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bjk_server.clock import KST
from bjk_server.db.models import (
    AuditFlag,
    Maintenance,
    Part,
    PurchaseOrder,
    Review,
    ReviewSnapshot,
)

DECISION_WAITING = ("reviewed", "held")
ORDER_CHECK_AFTER = timedelta(hours=24)
MAINTENANCE_CHECK_DAYS = 2


def _missed_orders(db: Session) -> dict[str, Any]:
    latest_snapshot = (
        select(ReviewSnapshot.values["t_deadline"].astext)
        .where(ReviewSnapshot.review_id == Review.id)
        .order_by(ReviewSnapshot.created_at.desc())
        .limit(1)
        .scalar_subquery()
    )
    rows = db.execute(
        select(Review, Part.name, latest_snapshot.label("t_deadline"))
        .outerjoin(Part, Part.id == Review.part_id)
        .where(Review.entry == "missed_draft", Review.status.in_(DECISION_WAITING))
        .order_by(Review.loss.desc(), Review.created_at, Review.id)
    ).all()
    items = [
        {
            "review_id": r.Review.id,
            "part": r.name,
            "verdict": r.Review.verdict,
            "flags": r.Review.flags,
            "t_deadline": date.fromisoformat(r.t_deadline) if r.t_deadline else None,
            "expected_loss": r.Review.loss,
        }
        for r in rows
    ]
    return {
        "count": len(items),
        "expected_loss_total": sum(i["expected_loss"] for i in items),
        "items": items,
    }


def build_briefing(db: Session, now: datetime) -> dict[str, Any]:
    """현재 트랜잭션의 회사(RLS) 기준 오늘 브리핑."""
    today = now.astimezone(KST).date()
    missed = _missed_orders(db)
    pending = db.scalar(
        select(func.count()).where(
            Review.entry != "missed_draft", Review.status.in_(DECISION_WAITING)
        )
    )
    count_needed = db.scalar(select(func.count()).where(AuditFlag.status == "open"))
    order_check = db.scalar(
        select(func.count()).where(
            PurchaseOrder.status == "approved",
            PurchaseOrder.approved_at <= now - ORDER_CHECK_AFTER,
        )
    )
    maintenance_check = db.scalar(
        select(func.count()).where(
            Maintenance.completed_at.is_(None),
            Maintenance.scheduled_date <= today - timedelta(days=MAINTENANCE_CHECK_DAYS),
        )
    )
    counts = (missed["count"], pending, count_needed, order_check, maintenance_check)
    return {
        "date": today,
        "generated_at": now.astimezone(KST),
        "should_notify": any(counts),
        "missed_orders": missed,
        "pending_reviews": pending,
        "count_needed": count_needed,
        "order_check_needed": order_check,
        "maintenance_check_needed": maintenance_check,
    }


def briefing_title(briefing: dict[str, Any]) -> str:
    parts = []
    if briefing["missed_orders"]["count"]:
        parts.append(f"놓친 발주 {briefing['missed_orders']['count']}건")
    if briefing["pending_reviews"]:
        parts.append(f"검토 대기 {briefing['pending_reviews']}건")
    if briefing["count_needed"]:
        parts.append(f"실사 필요 {briefing['count_needed']}건")
    if briefing["order_check_needed"]:
        parts.append(f"주문 확인 {briefing['order_check_needed']}건")
    if briefing["maintenance_check_needed"]:
        parts.append(f"정비 완료 확인 {briefing['maintenance_check_needed']}건")
    return "오늘 확인할 일: " + ", ".join(parts)
