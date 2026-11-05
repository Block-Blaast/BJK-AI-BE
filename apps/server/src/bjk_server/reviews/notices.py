"""검토 결과 알림 (기능명세서 F-NOTI-01·04).

| 결과 | 받는 사람 | 종류 |
| --- | --- | --- |
| 긴급(C-08)인 직원 요청·재고 부족 초안 | 사장님·관리자 | `review_urgent` 즉시 |
| 그 밖의 직원 요청 | 사장님·관리자 | `review_completed` 즉시 |
| 일반 재고 부족 초안, 놓친 발주 | 없음 | 아침 브리핑 검토 대기·놓친 발주 건수로 알린다 |
| 보류 | 요청자 | `decision_result`(채팅). 보완을 기다린다 |

요청자 본인은 사장님·관리자 알림에서 뺀다. 놓친 발주는 정의상 대부분 긴급이라 즉시 보내면
07:00 스캔 직후 몰리므로 07:30 브리핑에만 싣는다.
"""

import uuid
from datetime import datetime

from bjk_contracts import Flag
from bjk_review import ReviewOutcome
from sqlalchemy import select
from sqlalchemy.orm import Session

from bjk_server.db.models import Review, User
from bjk_server.notify.service import notify

VERDICT = {"ok": "적정", "revise": "수정 권고"}
IMMEDIATE = {"staff_request"}
URGENT_IMMEDIATE = {"staff_request", "stock_draft"}


def _deciders(db: Session, review: Review) -> list[uuid.UUID]:
    stmt = select(User.id).where(User.active, User.role.in_(("manager", "owner")))
    if review.requested_by is not None:
        stmt = stmt.where(User.id != review.requested_by)
    return list(db.scalars(stmt))


def notify_review_result(db: Session, review: Review, outcome: ReviewOutcome, now: datetime):
    """저장한 검토 결과로 알림을 만든다. 검토 저장과 같은 트랜잭션에서 부른다."""
    result, snapshot = outcome.result, outcome.snapshot
    name = snapshot.part_name or "요청한 부품"
    target = ("review", review.id)
    if review.status == "held":
        if review.requested_by is None:
            return
        # 보완 후 다시 보류될 수 있어 스냅샷 해시마다 한 번
        notify(
            db,
            review.company_id,
            [review.requested_by],
            "decision_result",
            f"{name} 발주 요청이 보류됐어요. 내 요청에서 내용을 보완해 주세요.",
            now,
            channels=("chat",),
            target=target,
            dedupe_key=f"review_held:{review.id}:{result.review_hash}",
        )
        return
    if Flag.URGENT in result.flags and review.entry in URGENT_IMMEDIATE:
        deadline = snapshot.t_deadline
        due = f" 마감 {deadline.month}/{deadline.day}" if deadline else ""
        notify(
            db,
            review.company_id,
            _deciders(db, review),
            "review_urgent",
            f"긴급: {name} 발주{due}. 검토 결과를 확인해 주세요.",
            now,
            target=target,
            dedupe_key=f"review_urgent:{review.id}",
        )
    elif review.entry in IMMEDIATE:
        notify(
            db,
            review.company_id,
            _deciders(db, review),
            "review_completed",
            f"{name} 발주 요청 검토가 끝났어요. 판정: {VERDICT[result.verdict]}",
            now,
            target=target,
            dedupe_key=f"review_completed:{review.id}",
        )
