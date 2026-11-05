"""검토 후속 질문 API (API 명세서 REV-06). MVP는 같은 스냅샷 숫자로 양식 답변만 한다."""

import uuid
from typing import Annotated

from bjk_review import Answer, answer_question
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from bjk_server.auth import TenantDB, require_role
from bjk_server.db.models import Review
from bjk_server.errors import ApiError, ErrorCode
from bjk_server.reviews.service import stored_review
from bjk_server.security import TokenClaims

router = APIRouter(prefix="/reviews", tags=["reviews"])

Manager = Annotated[TokenClaims, Depends(require_role("manager"))]


class QuestionRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)


@router.post("/{review_id}/questions", response_model=Answer)
def ask_question(review_id: uuid.UUID, body: QuestionRequest, _: Manager, db: TenantDB) -> Answer:
    """REV-06. 주제(수량·공급사·단가·긴급·리스크)로 분류하고 저장한 스냅샷 근거로만 답한다.

    분류되지 않거나 근거가 없으면(보류 건 포함) "근거 데이터에 없습니다."
    """
    review = db.get(Review, review_id)
    if review is None:
        raise ApiError(ErrorCode.NOT_FOUND, "검토를 찾을 수 없습니다.")
    stored = stored_review(db, review)
    if stored is None:
        raise ApiError(
            ErrorCode.REVIEW_NOT_DECIDABLE,
            "검토가 끝난 뒤 질문할 수 있습니다.",
            {"status": review.status},
        )
    result, snapshot = stored
    return answer_question(body.question, result, snapshot)
