"""채팅 기록 API (API 명세서 3-3 CHAT)."""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from bjk_server import clock, idempotency, ratelimit
from bjk_server.auth import CurrentUser, TenantDB
from bjk_server.chat.interpreter import Interpreter, get_interpreter
from bjk_server.chat.records import (
    RecordResponse,
    learn_alias,
    movement_out,
    record_movement,
    resolve_equipment,
    resolve_part,
)
from bjk_server.chat.schemas import MessageRequest, MessageResponse
from bjk_server.chat.service import handle_message
from bjk_server.db.models import ChatEntry
from bjk_server.errors import ApiError, ErrorCode
from bjk_server.security import TokenClaims

router = APIRouter(prefix="/chat", tags=["chat"])

MESSAGES_PER_MINUTE = 20


@router.post("/messages", response_model=MessageResponse)
def post_message(
    body: MessageRequest,
    user: CurrentUser,
    db: TenantDB,
    interpreter: Annotated[Interpreter, Depends(get_interpreter)],
):
    """CHAT-01. 메시지 → 추출 결과·확인 카드. 해석 실패 시 폼 입력 카드로 대체."""
    ratelimit.hit(db.get_bind(), f"chat:{user.user_id}", MESSAGES_PER_MINUTE, 60)
    stored = idempotency.claim(
        db, user.company_id, "chat_message", body.client_message_id, user.user_id,
        body.model_dump(mode="json"),
    )
    if stored:
        return JSONResponse(stored.body, stored.status_code)
    result = handle_message(db, user, body.client_message_id, body.text, interpreter)
    idempotency.complete(
        db,
        user.company_id,
        "chat_message",
        body.client_message_id,
        200,
        result.model_dump(mode="json"),
    )
    return result


class ConfirmRequest(BaseModel):
    """선택·수정한 값만 보낸다. 비우면 카드의 값을 쓴다."""

    part_id: uuid.UUID | None = None
    qty: int | None = Field(default=None, ge=1)
    equipment_id: uuid.UUID | None = None


def _own_entry(db: Session, user: TokenClaims, entry_id: uuid.UUID) -> ChatEntry:
    entry = db.scalar(select(ChatEntry).where(ChatEntry.id == entry_id).with_for_update())
    # 다른 사람의 카드는 없는 것으로 취급한다.
    if entry is None or entry.user_id != user.user_id:
        raise ApiError(ErrorCode.NOT_FOUND, "확인 카드를 찾을 수 없습니다.")
    if entry.status != "open":
        raise ApiError(
            ErrorCode.ALREADY_CONFIRMED, "이미 처리된 카드입니다.", {"status": entry.status}
        )
    return entry


def _uuid(value: str | None) -> uuid.UUID | None:
    return uuid.UUID(value) if value else None


@router.post("/entries/{entry_id}/confirm", response_model=RecordResponse)
def confirm_entry(
    entry_id: uuid.UUID, body: ConfirmRequest, user: CurrentUser, db: TenantDB
) -> RecordResponse:
    """CHAT-03. 확인 카드 확정 → 의도별 처리 (현재 OUT·IN)."""
    now = clock.utcnow()
    entry = _own_entry(db, user, entry_id)
    if entry.expires_at <= now:
        raise ApiError(ErrorCode.ENTRY_EXPIRED, "다시 보내 주세요.")
    if entry.type == "form" or entry.intent not in ("OUT", "IN"):
        raise ApiError(
            ErrorCode.VALIDATION_ERROR, "이 카드는 폼 입력으로 기록해 주세요.", {"type": entry.type}
        )

    payload = entry.payload
    part_id = body.part_id or _uuid(payload.get("part_id"))
    if (
        entry.type == "select"
        and body.part_id
        and str(body.part_id) not in payload["candidate_ids"]
    ):
        raise ApiError(ErrorCode.PART_NOT_RESOLVED, "후보 중에서 골라 주세요.")
    part = resolve_part(db, part_id)
    qty = body.qty or payload.get("qty")
    if not qty:
        raise ApiError(ErrorCode.VALIDATION_ERROR, "수량을 입력해 주세요.", {"field": "qty"})
    equipment_id = resolve_equipment(db, body.equipment_id or _uuid(payload.get("equipment_id")))

    intent: Literal["IN", "OUT"] = entry.intent
    movement, stock, reply = record_movement(
        db, user, intent, part, qty, equipment_id, payload.get("source_text")
    )
    result = RecordResponse(
        intent=intent,
        movement=movement_out(movement),
        stock_after=stock,
        reply=reply,
        alias_learned=learn_alias(db, payload.get("part_text"), part),
    )
    entry.status, entry.decided_at = "confirmed", now
    entry.result = result.model_dump(mode="json")
    return result


class CancelResponse(BaseModel):
    entry_id: uuid.UUID
    status: Literal["cancelled"]


@router.post("/entries/{entry_id}/cancel", response_model=CancelResponse)
def cancel_entry(entry_id: uuid.UUID, user: CurrentUser, db: TenantDB) -> CancelResponse:
    """CHAT-04. 확인 카드 취소. 원장은 바뀌지 않는다."""
    entry = _own_entry(db, user, entry_id)
    entry.status, entry.decided_at = "cancelled", clock.utcnow()
    return CancelResponse(entry_id=entry.id, status="cancelled")


class FormEntryRequest(BaseModel):
    client_message_id: str = Field(min_length=1, max_length=128)
    type: Literal["OUT", "IN"]
    part_id: uuid.UUID
    qty: int = Field(ge=1)
    equipment_id: uuid.UUID | None = None


@router.post("/entries", response_model=RecordResponse)
def form_entry(body: FormEntryRequest, user: CurrentUser, db: TenantDB):
    """CHAT-05. 폼 입력. 확인 카드 없이 바로 기록한다(ai 실패 시 대체 경로)."""
    stored = idempotency.claim(
        db, user.company_id, "chat_entry", body.client_message_id, user.user_id,
        body.model_dump(mode="json"),
    )
    if stored:
        return JSONResponse(stored.body, stored.status_code)

    part = resolve_part(db, body.part_id)
    equipment_id = resolve_equipment(db, body.equipment_id)
    movement, stock, reply = record_movement(
        db, user, body.type, part, body.qty, equipment_id, source_text=None
    )
    result = RecordResponse(
        intent=body.type, movement=movement_out(movement), stock_after=stock, reply=reply
    )
    now = clock.utcnow()
    db.add(
        ChatEntry(
            company_id=user.company_id,
            user_id=user.user_id,
            type="form",
            intent=body.type,
            status="confirmed",
            payload=body.model_dump(mode="json"),
            expires_at=now,
            decided_at=now,
            result=result.model_dump(mode="json"),
        )
    )
    body_json = result.model_dump(mode="json")
    idempotency.complete(db, user.company_id, "chat_entry", body.client_message_id, 200, body_json)
    return result
