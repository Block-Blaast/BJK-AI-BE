"""결재용 PDF API (API 명세서 REV-07)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response

from bjk_server.auth import TenantDB, require_role
from bjk_server.db.models import Part, Review, User
from bjk_server.errors import ApiError, ErrorCode
from bjk_server.reviews.pdf import Approval, render_pdf, review_html
from bjk_server.reviews.service import stored_review
from bjk_server.security import TokenClaims

router = APIRouter(prefix="/reviews", tags=["reviews"])

Manager = Annotated[TokenClaims, Depends(require_role("manager"))]


@router.get(
    "/{review_id}/pdf",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
)
def review_pdf(review_id: uuid.UUID, _: Manager, db: TenantDB) -> Response:
    """REV-07. 승인된 검토의 결재용 PDF. 저장한 스냅샷·승인 기록만 써서 다시 받아도 같다."""
    review = db.get(Review, review_id)
    if review is None:
        raise ApiError(ErrorCode.NOT_FOUND, "검토를 찾을 수 없습니다.")
    stored = stored_review(db, review) if review.status == "approved" else None
    if stored is None or review.decided_at is None:
        raise ApiError(
            ErrorCode.PDF_NOT_READY, "승인 후에 PDF를 만들 수 있습니다.", {"status": review.status}
        )
    result, snapshot = stored
    part = db.get(Part, review.part_id)
    approver = db.get(User, review.decided_by)
    html = review_html(
        part_name=part.name,
        entry=review.entry,
        result=result,
        snapshot=snapshot,
        opinion=review.opinion or {},
        approval=Approval(
            approver=approver.name,
            decided_at=review.decided_at,
            action=(review.decision or {}).get("action"),
        ),
    )
    return Response(
        render_pdf(html),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="review-{review.id}.pdf"'},
    )
