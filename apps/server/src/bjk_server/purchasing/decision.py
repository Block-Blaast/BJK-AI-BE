"""발주 검토 결정과 발주 생성 (API 명세서 REV-05, F-APPROVAL-01·02·03, F-REVIEW-09).

결정은 `reviewed` 검토에서만 받는다. 검토 행을 잠그고 상태를 확인하므로 동시에 두 번 결정하면
두 번째는 `REVIEW_ALREADY_DECIDED`다. 결정 직전에 스냅샷이 24시간을 넘었거나 같은 부품 입출고가
있었으면 근거를 다시 모아 판정한다. 판정·수정안이 바뀌면 새 스냅샷을 저장하고 다시 확인받는다
(`SNAPSHOT_REFRESHED`, 이 경우 결정은 하지 않는다).
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from bjk_review import (
    Line,
    OrderRequest,
    ReviewResult,
    ReviewSettings,
    decision_changed,
    needs_refresh,
    recheck,
    run_review,
    template_opinion,
    to_opinion_request,
)
from bjk_review import ReviewSnapshot as SnapshotValues
from pydantic import BaseModel, Field
from sqlalchemy import exists, or_, select
from sqlalchemy.orm import Session

from bjk_server.db.models import Movement, Part, PurchaseOrder, Review, ReviewSnapshot, Supplier
from bjk_server.domain.purchase_order import order_message
from bjk_server.errors import ApiError, ErrorCode
from bjk_server.events import publish
from bjk_server.notify.service import notify
from bjk_server.reviews.service import company_settings, review_settings, stored_review
from bjk_server.reviews.snapshot import collect_snapshot
from bjk_server.security import TokenClaims

Action = Literal[
    "approve_proposal",
    "approve_original",
    "approve_edited",
    "approve_alternative",
    "accept_no_order",
    "reject",
]
APPROVALS = {"approve_proposal", "approve_original", "approve_edited", "approve_alternative"}


class EditedOrder(BaseModel):
    qty: int = Field(ge=1)
    supplier_id: uuid.UUID | None = None
    unit_price: int | None = Field(default=None, ge=0)


class DecisionRequest(BaseModel):
    action: Action
    snapshot_hash: str | None = None
    edited: EditedOrder | None = None
    recheck_hash: str | None = None
    alternative_id: str | None = None
    reason: str | None = Field(default=None, max_length=500)


class SupplierRef(BaseModel):
    id: uuid.UUID
    name: str


class CreatedOrder(BaseModel):
    id: uuid.UUID
    status: str
    part_id: uuid.UUID
    qty: int
    supplier: SupplierRef
    unit_price: int
    total: int
    saving: int
    order_message: str
    pdf_url: str


class DecisionResponse(BaseModel):
    review_id: uuid.UUID
    status: Literal["approved", "closed"]
    purchase_order: CreatedOrder | None
    requester_notified: bool


@dataclass(frozen=True)
class Refreshed:
    """다시 모은 근거로 판정이 바뀌어 결정하지 않은 경우. 새 스냅샷은 저장했다."""

    verdict: str
    flags: list[str]
    snapshot_hash: str
    proposal: dict[str, Any] | None


def _not_decidable(review: Review) -> ApiError:
    if review.status in ("approved", "closed"):
        return ApiError(
            ErrorCode.REVIEW_ALREADY_DECIDED, "이미 결정한 검토입니다.", {"status": review.status}
        )
    return ApiError(
        ErrorCode.REVIEW_NOT_DECIDABLE,
        "검토가 끝난 건만 결정할 수 있습니다.",
        {"status": review.status},
    )


def _latest_snapshot(db: Session, review_id: uuid.UUID) -> ReviewSnapshot:
    row = db.scalar(
        select(ReviewSnapshot)
        .where(ReviewSnapshot.review_id == review_id)
        .order_by(ReviewSnapshot.created_at.desc(), ReviewSnapshot.id)
        .limit(1)
    )
    assert row is not None  # reviewed 검토에는 스냅샷이 있다
    return row


def _part_moved_since(db: Session, part_id: uuid.UUID | None, since: datetime) -> bool:
    if part_id is None:
        return False
    merged = select(Part.id).where(or_(Part.id == part_id, Part.merged_into == part_id))
    return bool(
        db.scalar(select(exists().where(Movement.part_id.in_(merged), Movement.created_at > since)))
    )


def _proposal_out(result: ReviewResult) -> dict[str, Any] | None:
    p = result.proposal
    if p is None:
        return None
    return {
        "qty": p.qty,
        "supplier_id": p.supplier_id,
        "unit_price": p.unit_price,
        "total": p.total,
    }


def _refresh(
    db: Session, review: Review, row: ReviewSnapshot, result: ReviewResult, now: datetime
) -> tuple[ReviewResult, SnapshotValues, ReviewSettings, Refreshed | None]:
    """필요하면 근거를 다시 모아 판정한다. 바뀌지 않았으면 새 결과로 계속 결정한다."""
    snapshot = SnapshotValues.model_validate(row.values)
    settings = ReviewSettings.model_validate(row.settings)
    moved = _part_moved_since(db, review.part_id, row.created_at)
    if not needs_refresh(snapshot, now=now, part_moved_since=moved):
        return result, snapshot, settings, None
    order = OrderRequest.model_validate(review.request)
    company = company_settings(db, review.company_id)
    settings = review_settings(company)
    part_id = str(review.part_id) if review.part_id else None
    fresh = collect_snapshot(db, part_id, order, now=now, settings=company, review_id=review.id)
    after = run_review(fresh, order, settings)
    db.add(
        ReviewSnapshot(
            company_id=review.company_id,
            review_id=review.id,
            hash=after.review_hash,
            values=fresh.model_dump(mode="json"),
            settings=settings.model_dump(mode="json"),
            computed_at=fresh.computed_at,
        )
    )
    if not decision_changed(result, after):
        return after, fresh, settings, None
    review.verdict, review.flags = after.verdict, list(after.flags)
    review.hold_reasons = list(after.hold_reasons)
    review.status = "held" if after.verdict == "hold" else "reviewed"
    review.result = after.model_dump(
        mode="json", exclude={"verdict", "flags", "hold_reasons", "review_hash"}
    )
    text = template_opinion(to_opinion_request(after, fresh, company_id=review.company_id))
    review.opinion = {"text": text, "source": "template", "verified": True}
    review.original_total = after.original.total
    review.saving = after.proposal.saving if after.proposal else 0
    review.loss = after.risk_if_not_ordered.loss
    review.updated_at = now
    return (
        after,
        fresh,
        settings,
        Refreshed(after.verdict, list(after.flags), after.review_hash, _proposal_out(after)),
    )


def _order_line(
    body: DecisionRequest, result: ReviewResult, snapshot: SnapshotValues, settings: ReviewSettings
) -> tuple[Line, int]:
    """승인 행동이 고른 발주 줄과 원안 대비 절감액."""
    original = result.original
    if body.action == "approve_original":
        return original, 0
    if body.action == "approve_proposal":
        if result.proposal is None or result.proposal.no_order:
            raise ApiError(
                ErrorCode.REVIEW_NOT_DECIDABLE,
                "발주할 수정안이 없습니다. 발주 불필요 수용이나 원안 승인을 골라 주세요.",
            )
        return result.proposal, result.proposal.saving
    if body.action == "approve_alternative":
        alt = next((a for a in result.alternatives if a.id == body.alternative_id), None)
        if alt is None:
            raise ApiError(
                ErrorCode.VALIDATION_ERROR,
                "대안을 찾을 수 없습니다.",
                {"alternative_id": body.alternative_id},
            )
        return alt, original.total - alt.total
    # approve_edited: 미리 본(REV-04) 결과와 같은 스냅샷·수정 값인지 해시로 확인한다
    assert body.edited is not None
    edited = OrderRequest(
        qty=body.edited.qty,
        supplier_id=str(body.edited.supplier_id) if body.edited.supplier_id else None,
        unit_price=body.edited.unit_price,
    )
    rechecked = recheck(snapshot, edited, settings)
    if rechecked.review_hash != body.recheck_hash:
        raise ApiError(
            ErrorCode.SNAPSHOT_REFRESHED,
            "근거가 바뀌었습니다. 다시 확인해 주세요.",
            {"recheck_hash": rechecked.review_hash, "verdict": rechecked.verdict},
        )
    return rechecked.original, original.total - rechecked.original.total


def _required_fields(body: DecisionRequest) -> None:
    if body.action == "reject" and not (body.reason or "").strip():
        raise ApiError(ErrorCode.REASON_REQUIRED, "반려 사유를 입력해 주세요.", {"field": "reason"})
    missing = {
        "approve_edited": [f for f in ("edited", "recheck_hash") if getattr(body, f) is None],
        "approve_alternative": ["alternative_id"] if body.alternative_id is None else [],
    }.get(body.action, [])
    if missing:
        raise ApiError(ErrorCode.VALIDATION_ERROR, "필수 값이 없습니다.", {"fields": missing})


def _create_order(
    db: Session, review: Review, user: TokenClaims, line: Line, saving: int, snapshot, now
) -> CreatedOrder:
    if line.qty <= 0 or line.supplier_id is None or line.unit_price is None:
        raise ApiError(
            ErrorCode.REVIEW_NOT_DECIDABLE,
            "공급사·단가·수량이 정해지지 않아 발주할 수 없습니다.",
            {"qty": line.qty, "supplier_id": line.supplier_id, "unit_price": line.unit_price},
        )
    supplier = db.get(Supplier, uuid.UUID(line.supplier_id))
    part = db.get(Part, review.part_id) if review.part_id else None
    if supplier is None or part is None:
        raise ApiError(ErrorCode.REVIEW_NOT_DECIDABLE, "부품이나 공급사를 찾을 수 없습니다.")
    order = PurchaseOrder(
        id=uuid.uuid4(),
        company_id=review.company_id,
        review_id=review.id,
        part_id=part.id,
        supplier_id=supplier.id,
        qty=line.qty,
        unit_price=line.unit_price,
        status="approved",
        approved_at=now,
        approved_by=user.user_id,
    )
    db.add(order)
    db.flush()
    return CreatedOrder(
        id=order.id,
        status="approved",
        part_id=part.id,
        qty=order.qty,
        supplier=SupplierRef(id=supplier.id, name=supplier.name),
        unit_price=order.unit_price,
        total=order.qty * order.unit_price,
        saving=saving,
        order_message=order_message(part.name, order.qty, part.unit, snapshot.t_out),
        pdf_url=f"/api/v1/reviews/{review.id}/pdf",
    )


RESULT_TITLES = {
    "approved": "발주 요청이 승인됐어요.",
    "no_order": "검토 결과 이번 발주는 필요 없어요.",
    "reject": "발주 요청이 반려됐어요.",
}


def decide(
    db: Session, user: TokenClaims, review_id: uuid.UUID, body: DecisionRequest, now: datetime
) -> DecisionResponse | Refreshed:
    """REV-05. 결정하거나, 근거가 바뀌었으면 Refreshed를 돌려준다(새 스냅샷은 저장)."""
    review = db.get(Review, review_id, with_for_update=True)
    if review is None:
        raise ApiError(ErrorCode.NOT_FOUND, "검토를 찾을 수 없습니다.")
    if review.status != "reviewed":
        raise _not_decidable(review)
    if user.role != "owner" and review.requested_by == user.user_id:
        raise ApiError(
            ErrorCode.SELF_APPROVAL_NOT_ALLOWED, "본인이 올린 요청은 사장님만 결정할 수 있습니다."
        )
    _required_fields(body)
    stored = stored_review(db, review)
    assert stored is not None
    row = _latest_snapshot(db, review.id)
    if body.snapshot_hash is not None and body.snapshot_hash != row.hash:
        result = stored[0]
        return Refreshed(result.verdict, list(result.flags), row.hash, _proposal_out(result))
    result, snapshot, settings, refreshed = _refresh(db, review, row, stored[0], now)
    if refreshed is not None:
        return refreshed

    order: CreatedOrder | None = None
    if body.action in APPROVALS:
        line, saving = _order_line(body, result, snapshot, settings)
        order = _create_order(db, review, user, line, saving, snapshot, now)
        review.status, outcome = "approved", "approved"
    else:
        review.status = "closed"
        outcome = "reject" if body.action == "reject" else "no_order"
    review.decision = {
        "action": body.action,
        "reason": (body.reason or "").strip() or None,
        "snapshot_hash": result.review_hash,
        "edited": body.edited.model_dump(mode="json") if body.edited else None,
        "alternative_id": body.alternative_id,
        "purchase_order_id": str(order.id) if order else None,
    }
    review.decided_by, review.decided_at, review.updated_at = user.user_id, now, now
    publish(
        db,
        review.company_id,
        "review.decided",
        {"review_id": str(review.id), "status": review.status, "action": body.action},
    )
    notified = False
    if review.requested_by is not None:
        title = RESULT_TITLES[outcome]
        if outcome == "reject":
            title = f"{title} 사유: {review.decision['reason']}"[:200]
        notified = bool(
            notify(
                db,
                review.company_id,
                [review.requested_by],
                "decision_result",
                title,
                now,
                channels=("chat", "in_app"),
                target=("review", review.id),
                dedupe_key=f"decision:{review.id}",
            )
        )
    return DecisionResponse(
        review_id=review.id,
        status=review.status,  # type: ignore[arg-type]
        purchase_order=order,
        requester_notified=notified,
    )
