"""채팅 기록 API (API 명세서 3-3 CHAT)."""

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from bjk_server import idempotency, ratelimit
from bjk_server.auth import CurrentUser, TenantDB
from bjk_server.chat.interpreter import Interpreter, get_interpreter
from bjk_server.chat.schemas import MessageRequest, MessageResponse
from bjk_server.chat.service import handle_message

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
    stored = idempotency.claim(db, user.company_id, "chat_message", body.client_message_id)
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
