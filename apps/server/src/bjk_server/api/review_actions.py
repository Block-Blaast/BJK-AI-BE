"""검토 보완·재실행 API (API 명세서 REV-03, REV-04). 조회·결정 API와 따로 둔다."""

import uuid
from typing import Annotated, Any

from bjk_review import OrderRequest, ProposalLine, ReviewSettings, recheck
from bjk_review import ReviewSnapshot as SnapshotValues
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from bjk_server import clock
from bjk_server.auth import ROLE_RANK, CurrentUser, TenantDB, require_role
from bjk_server.db.models import Part, Review, ReviewSnapshot, Supplier
from bjk_server.errors import ApiError, ErrorCode
from bjk_server.reviews.service import ReviewRunner, get_review_runner
from bjk_server.security import TokenClaims

router = APIRouter(prefix="/reviews", tags=["reviews"])

Manager = Annotated[TokenClaims, Depends(require_role("manager"))]
Runner = Annotated[ReviewRunner, Depends(get_review_runner)]


class ClarifyRequest(BaseModel):
    part_id: uuid.UUID | None = None
    supplier_id: uuid.UUID | None = None


class ClarifyResponse(BaseModel):
    review_id: uuid.UUID
    status: str


class RecheckRequest(BaseModel):
    qty: int = Field(ge=0)
    supplier_id: uuid.UUID | None = None
    unit_price: int | None = Field(default=None, ge=0)


class RecheckResponse(BaseModel):
    verdict: str
    flags: list[str]
    checks: list[dict[str, Any]]
    proposal: dict[str, Any] | None
    recheck_hash: str


def proposal_out(line: ProposalLine | None) -> dict[str, Any] | None:
    """REV-02 `proposal` 모양. 공급사는 `{id, name}`."""
    if line is None:
        return None
    supplier = {"id": line.supplier_id, "name": line.supplier_name} if line.supplier_id else None
    return {
        "qty": line.qty,
        "supplier": supplier,
        "unit_price": line.unit_price,
        "total": line.total,
        "saving": line.saving,
        "no_order": line.no_order,
        "basis": list(line.basis),
    }


def latest_snapshot(db: Session, review_id: uuid.UUID) -> ReviewSnapshot | None:
    return db.scalar(
        select(ReviewSnapshot)
        .where(ReviewSnapshot.review_id == review_id)
        .order_by(ReviewSnapshot.created_at.desc(), ReviewSnapshot.id)
        .limit(1)
    )


@router.post("/{review_id}/recheck", response_model=RecheckResponse)
def recheck_review(
    review_id: uuid.UUID, body: RecheckRequest, _: Manager, db: TenantDB
) -> RecheckResponse:
    """REV-04. 저장한 스냅샷·설정값으로 직접 수정 값을 다시 판정한다. 저장하지 않는다.

    같은 스냅샷·수정 값이면 같은 `recheck_hash`가 나와, 결정(`approve_edited`) 때 대조한다.
    """
    review = db.get(Review, review_id)
    if review is None:
        raise ApiError(ErrorCode.NOT_FOUND, "검토를 찾을 수 없습니다.")
    snapshot = latest_snapshot(db, review.id)
    if review.status != "reviewed" or snapshot is None:
        raise ApiError(
            ErrorCode.REVIEW_NOT_DECIDABLE,
            "검토가 끝난 건만 다시 볼 수 있습니다.",
            {"status": review.status},
        )
    edited = OrderRequest(
        qty=body.qty,
        supplier_id=str(body.supplier_id) if body.supplier_id else None,
        unit_price=body.unit_price,
    )
    result = recheck(
        SnapshotValues.model_validate(snapshot.values),
        edited,
        ReviewSettings.model_validate(snapshot.settings),
    )
    return RecheckResponse(
        verdict=result.verdict,
        flags=list(result.flags),
        checks=[c.model_dump(mode="json") for c in result.checks],
        proposal=proposal_out(result.proposal),
        recheck_hash=result.review_hash,
    )


def _visible_review(db: Session, user: TokenClaims, review_id: uuid.UUID) -> Review:
    """작업자는 본인 요청만 본다. 남의 검토는 있어도 404."""
    review = db.get(Review, review_id, with_for_update=True)
    is_manager = ROLE_RANK[user.role] >= ROLE_RANK["manager"]
    if review is None or not (is_manager or review.requested_by == user.user_id):
        raise ApiError(ErrorCode.NOT_FOUND, "검토를 찾을 수 없습니다.")
    return review


@router.post("/{review_id}/clarify", status_code=202, response_model=ClarifyResponse)
def clarify_review(
    review_id: uuid.UUID, body: ClarifyRequest, user: CurrentUser, db: TenantDB, runner: Runner
) -> ClarifyResponse:
    """REV-03. 보류 건에 부품·공급사를 보완하고 같은 검토를 다시 돌린다 (F-REVIEW-03).

    요청자 본인 또는 manager 이상. 다시 돌린 결과는 새 스냅샷 행으로 쌓인다.
    """
    review = _visible_review(db, user, review_id)
    if review.status != "held":
        raise ApiError(
            ErrorCode.REVIEW_NOT_DECIDABLE,
            "보류된 검토만 보완할 수 있습니다.",
            {"status": review.status},
        )
    if body.part_id is None and body.supplier_id is None:
        raise ApiError(
            ErrorCode.VALIDATION_ERROR,
            "보완할 부품이나 공급사가 필요합니다.",
            {"fields": ["part_id", "supplier_id"]},
        )
    if body.part_id is not None:
        part = db.get(Part, body.part_id)
        if part is None or part.merged_into is not None:
            raise ApiError(ErrorCode.VALIDATION_ERROR, "없는 부품입니다.", {"field": "part_id"})
        review.part_id = part.id
    if body.supplier_id is not None:
        if db.get(Supplier, body.supplier_id) is None:
            raise ApiError(
                ErrorCode.VALIDATION_ERROR, "없는 공급사입니다.", {"field": "supplier_id"}
            )
        review.request = {**review.request, "supplier_id": str(body.supplier_id)}
    review.status = "reviewing"
    review.verdict = review.result = review.opinion = review.expires_at = None
    review.flags, review.hold_reasons = [], []
    review.updated_at = clock.utcnow()
    db.flush()
    runner.start_after_commit(db, review.company_id, review.id)
    return ClarifyResponse(review_id=review.id, status=review.status)
