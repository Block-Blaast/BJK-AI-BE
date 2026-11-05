"""대시보드 오늘 활동 목록 (화면 W-01, 명세 밖, #275).

기능명세서에는 "오늘 활동" 요소만 있고 형식이 없어, 프론트가 쓰던 형식(`id`, `kind`, `text`, `at`,
`href`)으로 정했다. 건수는 DSH-02 `today`와 같은 기준(Asia/Seoul 오늘 0시부터)이다. 기록을
저장하지 않고 원장·검토·실사 요청에서 조회할 때 만든다.
"""

import uuid
from datetime import date, datetime, time
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select

from bjk_server import clock
from bjk_server.auth import TenantDB, require_role
from bjk_server.clock import KST
from bjk_server.db.models import CountRequest, Movement, Part, Review, User
from bjk_server.security import TokenClaims

router = APIRouter(prefix="/activity", tags=["activity"])

Manager = Annotated[TokenClaims, Depends(require_role("manager"))]
ActivityKind = Literal[
    "movement", "review_created", "review_decided", "audit_requested", "audit_resolved"
]
# 한 번에 주는 최대 개수. 오늘 하루치라 커서 없이 최신 순으로 자른다.
LIMIT = 100

MOVEMENT_TYPES = {"IN": "입고", "OUT": "출고", "ADJUST": "조정"}
ENTRIES = {
    "staff_request": "직원 요청",
    "stock_draft": "재고 부족 초안",
    "missed_draft": "놓친 발주",
}
VERDICTS = {"ok": "적정", "revise": "수정 권고", "hold": "보류"}
FLAGS = {"urgent": "긴급", "caution": "주의", "alternative": "대안"}
ACTIONS = {
    "approve_proposal": "수정안 승인",
    "approve_original": "원안 승인",
    "approve_edited": "직접 수정 승인",
    "approve_alternative": "대안 승인",
    "accept_no_order": "발주 불필요 수용",
    "reject": "반려",
}


class Activity(BaseModel):
    id: str
    kind: ActivityKind
    text: str
    at: datetime
    href: str | None


class TodayActivity(BaseModel):
    date: date
    items: list[Activity]


def _signed(qty: int, unit: str) -> str:
    return f"{'+' if qty > 0 else ''}{qty}{unit}"


@router.get("/today", response_model=TodayActivity)
def today_activity(_: Manager, db: TenantDB) -> TodayActivity:
    """오늘 원장 기록·검토 생성·결정·실사 요청·실사 종료. 최신 순 최대 100개."""
    now = clock.utcnow()
    today = now.astimezone(KST).date()
    start = datetime.combine(today, time.min, tzinfo=KST)
    parts: dict[uuid.UUID, Part] = {}

    def part(part_id: uuid.UUID | None) -> Part | None:
        if part_id is None:
            return None
        if part_id not in parts:
            parts[part_id] = db.get(Part, part_id)
        return parts[part_id]

    def name(part_id: uuid.UUID | None) -> str:
        p = part(part_id)
        return p.name if p else "부품 미확정"

    items: list[Activity] = []
    for m in db.scalars(select(Movement).where(Movement.occurred_at >= start)):
        p = part(m.part_id)
        label = m.reason if m.type == "ADJUST" and m.reason else MOVEMENT_TYPES[m.type]
        quote = f' — "{m.source_text}"' if m.source_text else ""
        items.append(
            Activity(
                id=str(m.id),
                kind="movement",
                text=f"{p.name} {label} {_signed(m.qty, p.unit)}{quote}",
                at=m.occurred_at,
                href=f"/parts/{m.part_id}",
            )
        )
    for r in db.scalars(select(Review).where(Review.created_at >= start)):
        verdict = VERDICTS.get(r.verdict, "검토 중") if r.verdict else "검토 중"
        flags = "".join(f" · {FLAGS[f]}" for f in r.flags or [] if f in FLAGS)
        items.append(
            Activity(
                id=f"rc-{r.id}",
                kind="review_created",
                text=f"{name(r.part_id)} {ENTRIES.get(r.entry, r.entry)} 검토 — {verdict}{flags}",
                at=r.created_at,
                href=f"/reviews/{r.id}",
            )
        )
    for r in db.scalars(select(Review).where(Review.decided_at >= start)):
        decision = r.decision or {}
        reason = f" — {decision['reason']}" if decision.get("reason") else ""
        action = ACTIONS.get(decision.get("action"), "결정")
        items.append(
            Activity(
                id=f"rd-{r.id}",
                kind="review_decided",
                text=f"{name(r.part_id)} {action}{reason}",
                at=r.decided_at,
                href=f"/reviews/{r.id}",
            )
        )
    counts = db.scalars(
        select(CountRequest).where(
            (CountRequest.created_at >= start) | (CountRequest.closed_at >= start)
        )
    ).all()
    for c in counts:
        p = part(c.part_id)
        if c.created_at >= start:
            assignee = db.get(User, c.assignee_id)
            items.append(
                Activity(
                    id=f"aq-{c.id}",
                    kind="audit_requested",
                    text=f"{p.name} 실사 요청 → {assignee.name}",
                    at=c.created_at,
                    href="/audit",
                )
            )
        if c.closed_at is not None and c.closed_at >= start:
            result = f"차이 {_signed(c.diff, p.unit)}" if c.diff else "이상 없음"
            items.append(
                Activity(
                    id=f"ar-{c.id}",
                    kind="audit_resolved",
                    text=f"{p.name} 실사 종료 — {result}",
                    at=c.closed_at,
                    href="/audit",
                )
            )
    items.sort(key=lambda a: (a.at, a.id), reverse=True)
    return TodayActivity(date=today, items=items[:LIMIT])
