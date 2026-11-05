"""채팅 메시지 처리: 해석 → 의도별 처리기 → 답변·확인 카드 (API 명세서 CHAT-01)."""

import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from bjk_server import clock
from bjk_server.chat.intents import HANDLERS, IntentContext, IntentResult
from bjk_server.chat.interpreter import Interpreter, InterpreterUnavailable
from bjk_server.chat.matching import QueryEmbedder
from bjk_server.chat.schemas import AiStatus, Card, MessageResponse
from bjk_server.db.models import ChatMessage
from bjk_server.security import TokenClaims

HELP_REPLY = "기록, 조회, 발주 요청을 도와드려요."
FORM_REPLY = "자동으로 해석하지 못했어요. 입력 폼으로 기록해 주세요."


def handle_message(
    db: Session,
    user: TokenClaims,
    client_message_id: str,
    text: str,
    interpreter: Interpreter,
    now: datetime | None = None,
    embedder: QueryEmbedder | None = None,
) -> MessageResponse:
    now = now or clock.utcnow()
    message_id = uuid.uuid4()
    try:
        parsed = interpreter.interpret(text)
        ai = AiStatus(used=True, fallback=False)
    except InterpreterUnavailable as exc:
        parsed = None
        ai = AiStatus(used=True, fallback=True, reason=exc.reason)

    db.add(
        ChatMessage(
            id=message_id,
            company_id=user.company_id,
            user_id=user.user_id,
            client_message_id=client_message_id,
            text=text,
            intent=parsed.intent if parsed else "OTHER",
            reply="",
            ai=ai.model_dump(),
        )
    )
    db.flush()

    ctx = IntentContext(db, user, message_id, text, now, embedder)
    if parsed is None:
        intent = "OTHER"
        entry = ctx.add_entry("form", "OTHER", {"source_text": text})
        card = Card(type="form", entry_id=entry.id, intent="OTHER", expires_at=entry.expires_at)
        result = IntentResult(FORM_REPLY, [card])
    else:
        intent = parsed.intent
        handler = HANDLERS.get(intent)
        # 처리기가 없는 의도(PURCHASE_REQUEST 등)는 도움말로 답한다.
        result = handler(ctx, parsed) if handler else IntentResult(HELP_REPLY)

    db.get(ChatMessage, message_id).reply = result.reply
    db.flush()
    return MessageResponse(
        message_id=message_id,
        intent=intent,
        reply=result.reply,
        cards=result.cards,
        ai=ai,
        count_request_id=result.count_request_id,
    )
