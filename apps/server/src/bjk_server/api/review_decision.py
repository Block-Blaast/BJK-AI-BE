"""발주 검토 결정 API (API 명세서 REV-05). 결정 규칙은 purchasing/decision."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse

from bjk_server import clock, idempotency
from bjk_server.auth import TenantDB, require_role
from bjk_server.errors import STATUS, ApiError, ErrorCode, error_body
from bjk_server.purchasing.decision import DecisionRequest, DecisionResponse, Refreshed, decide
from bjk_server.security import TokenClaims

router = APIRouter(prefix="/reviews", tags=["reviews"])

Manager = Annotated[TokenClaims, Depends(require_role("manager"))]
SCOPE = "review_decision"


@router.post(
    "/{review_id}/decision",
    response_model=DecisionResponse,
    responses={201: {"model": DecisionResponse}},
)
def decide_review(
    review_id: uuid.UUID,
    body: DecisionRequest,
    user: Manager,
    db: TenantDB,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key", max_length=128)] = None,
):
    """REV-05. 승인이면 `approved` 발주를 만들어 201, 종료(불필요 수용·반려)면 200.

    근거가 바뀌어 다시 확인받아야 하면 409 `SNAPSHOT_REFRESHED`. 새 스냅샷은 저장한 채로 돌려준다.
    같은 `Idempotency-Key`로 다시 보내면 처음 응답을 그대로 돌려준다.
    """
    if not idempotency_key:
        raise ApiError(
            ErrorCode.VALIDATION_ERROR,
            "Idempotency-Key 헤더가 필요합니다.",
            {"header": "Idempotency-Key"},
        )
    request = {"review_id": str(review_id), **body.model_dump(mode="json")}
    stored = idempotency.claim(db, user.company_id, SCOPE, idempotency_key, user.user_id, request)
    if stored:
        return JSONResponse(stored.body, stored.status_code)

    outcome = decide(db, user, review_id, body, clock.utcnow())
    if isinstance(outcome, Refreshed):
        status = STATUS[ErrorCode.SNAPSHOT_REFRESHED]
        payload = error_body(
            ErrorCode.SNAPSHOT_REFRESHED,
            "근거를 새로 모았더니 판정이 바뀌었어요. 다시 확인해 주세요.",
            {
                "verdict": outcome.verdict,
                "flags": outcome.flags,
                "snapshot_hash": outcome.snapshot_hash,
                "proposal": outcome.proposal,
            },
        )
    else:
        status = 201 if outcome.purchase_order else 200
        payload = outcome.model_dump(mode="json")
    idempotency.complete(db, user.company_id, SCOPE, idempotency_key, status, payload)
    return JSONResponse(payload, status)
