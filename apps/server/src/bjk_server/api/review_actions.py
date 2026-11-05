"""검토 재실행 API (API 명세서 REV-04). 조회·결정 API와 따로 둔다."""

import uuid
from typing import Annotated, Any

from bjk_review import OrderRequest, ProposalLine, ReviewSettings, recheck
from bjk_review import ReviewSnapshot as SnapshotValues
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from bjk_server.auth import TenantDB, require_role
from bjk_server.db.models import Review, ReviewSnapshot
from bjk_server.errors import ApiError, ErrorCode
from bjk_server.security import TokenClaims

router = APIRouter(prefix="/reviews", tags=["reviews"])

Manager = Annotated[TokenClaims, Depends(require_role("manager"))]


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
