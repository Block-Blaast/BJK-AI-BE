"""원장 정정 API (API 명세서 3-4 LED)."""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from bjk_server import clock
from bjk_server.auth import TenantDB, require_role
from bjk_server.db.models import Movement
from bjk_server.errors import ApiError, ErrorCode
from bjk_server.inventory import stock_of
from bjk_server.security import TokenClaims

router = APIRouter(prefix="/movements", tags=["ledger"])

Manager = Annotated[TokenClaims, Depends(require_role("manager"))]


class CorrectionRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
    # 원본이 원래 가져야 했던 부호 있는 수량. 출고는 0 이하, 입고는 0 이상.
    corrected_qty: int


class CorrectionMovement(BaseModel):
    id: uuid.UUID
    type: Literal["ADJUST"]
    qty: int
    reason: str
    corrects: uuid.UUID


class CorrectionResponse(BaseModel):
    movement: CorrectionMovement
    stock_after: int


@router.post("/{movement_id}/correction", status_code=201, response_model=CorrectionResponse)
def correct_movement(
    movement_id: uuid.UUID, body: CorrectionRequest, user: Manager, db: TenantDB
) -> CorrectionResponse:
    """LED-02. 원본은 그대로 두고 차이만큼 반대 방향 ADJUST를 더한다 (F-LEDGER-01).

    같은 원본을 다시 정정하면 앞선 정정까지 합친 현재 수량과 corrected_qty의 차이만 더한다.
    """
    original = db.get(Movement, movement_id)
    if original is None:
        raise ApiError(ErrorCode.NOT_FOUND, "원장 기록을 찾을 수 없습니다.")
    if original.corrects_id is not None:
        raise ApiError(
            ErrorCode.VALIDATION_ERROR,
            "정정 기록이 아닌 원본 기록을 정정해 주세요.",
            {"corrects": str(original.corrects_id)},
        )
    reason = body.reason.strip()
    if not reason:
        raise ApiError(
            ErrorCode.VALIDATION_ERROR, "정정 사유를 입력해 주세요.", {"field": "reason"}
        )
    if (original.type == "OUT" and body.corrected_qty > 0) or (
        original.type == "IN" and body.corrected_qty < 0
    ):
        raise ApiError(
            ErrorCode.VALIDATION_ERROR,
            "정정 수량의 부호가 원본 유형과 맞지 않습니다.",
            {"type": original.type, "corrected_qty": body.corrected_qty},
        )
    # 원장은 UPDATE 권한이 없어 행 잠금 대신 원본별 advisory lock으로 동시 정정을 막는다.
    db.execute(select(func.pg_advisory_xact_lock(func.hashtext(f"correction:{original.id}"))))
    corrected_so_far = db.scalar(
        select(func.coalesce(func.sum(Movement.qty), 0)).where(Movement.corrects_id == original.id)
    )
    diff = body.corrected_qty - (original.qty + corrected_so_far)
    if diff == 0:
        raise ApiError(
            ErrorCode.VALIDATION_ERROR,
            "정정할 차이가 없습니다.",
            {"current_qty": original.qty + corrected_so_far},
        )
    correction = Movement(
        id=uuid.uuid4(),
        company_id=original.company_id,
        part_id=original.part_id,
        type="ADJUST",
        qty=diff,
        occurred_at=clock.utcnow(),
        author_id=user.user_id,
        reason=reason,
        corrects_id=original.id,
    )
    db.add(correction)
    db.flush()
    return CorrectionResponse(
        movement=CorrectionMovement(
            id=correction.id, type="ADJUST", qty=diff, reason=reason, corrects=original.id
        ),
        stock_after=stock_of(db, original.part_id),
    )
