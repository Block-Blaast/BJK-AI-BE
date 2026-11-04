"""채팅 메시지 처리: 해석 → 부품 매칭 → 확인 카드 (API 명세서 CHAT-01)."""

import uuid
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from bjk_server import clock
from bjk_server.chat.interpreter import Interpretation, Interpreter, InterpreterUnavailable
from bjk_server.chat.matching import Candidate, find_candidates, find_equipment
from bjk_server.chat.schemas import (
    AiStatus,
    CandidateOut,
    Card,
    CardType,
    EquipmentRef,
    MessageResponse,
)
from bjk_server.clock import KST
from bjk_server.db.models import ChatEntry, ChatMessage, Equipment
from bjk_server.security import TokenClaims

CARD_TTL = timedelta(minutes=10)
RECORD_INTENTS = ("OUT", "IN")
HELP_REPLY = "기록, 조회, 발주 요청을 도와드려요."
FORM_REPLY = "자동으로 해석하지 못했어요. 입력 폼으로 기록해 주세요."


def _add_entry(
    db: Session,
    user: TokenClaims,
    message_id: uuid.UUID,
    type_: CardType,
    intent: str,
    payload: dict,
    now: datetime,
) -> ChatEntry:
    entry = ChatEntry(
        id=uuid.uuid4(),
        company_id=user.company_id,
        message_id=message_id,
        user_id=user.user_id,
        type=type_,
        intent=intent,
        payload=payload,
        expires_at=now + CARD_TTL,
    )
    db.add(entry)
    return entry


def _equipment_ref(equipment: Equipment | None) -> EquipmentRef | None:
    return EquipmentRef(id=equipment.id, name=equipment.name) if equipment else None


def _record_card(
    db: Session,
    user: TokenClaims,
    message_id: uuid.UUID,
    parsed: Interpretation,
    text: str,
    now: datetime,
) -> tuple[str, Card]:
    """출고·입고 메시지의 확인 카드와 답변."""
    equipment = find_equipment(db, parsed.equipment_text)
    candidates = find_candidates(db, parsed.part_text, equipment.id if equipment else None)
    common = {
        "intent": parsed.intent,
        "part_text": parsed.part_text,
        "qty": parsed.qty,
        "equipment": _equipment_ref(equipment),
    }
    payload = {
        "part_text": parsed.part_text,
        "qty": parsed.qty,
        "equipment_id": str(equipment.id) if equipment else None,
        "source_text": text,
    }

    if not candidates:
        entry = _add_entry(db, user, message_id, "unregistered", parsed.intent, payload, now)
        label = parsed.part_text or "부품"
        reply = f"'{label}'은(는) 등록되지 않은 부품이에요. 관리자에게 등록을 요청해 주세요."
        return reply, Card(
            type="unregistered", entry_id=entry.id, expires_at=entry.expires_at, **common
        )

    if len(candidates) > 1:
        payload["candidate_ids"] = [str(c.part_id) for c in candidates]
        entry = _add_entry(db, user, message_id, "select", parsed.intent, payload, now)
        card = Card(
            type="select",
            entry_id=entry.id,
            expires_at=entry.expires_at,
            candidates=[_candidate_out(c) for c in candidates],
            **common,
        )
        return f"어떤 {parsed.part_text}인가요?", card

    part = candidates[0]
    payload["part_id"] = str(part.part_id)
    short = parsed.intent == "OUT" and parsed.qty is not None and parsed.qty > part.stock
    type_: CardType = "warning" if short else "confirm"
    entry = _add_entry(db, user, message_id, type_, parsed.intent, payload, now)
    action = "출고" if parsed.intent == "OUT" else "입고"
    qty = f" {parsed.qty}{part.unit}" if parsed.qty is not None else ""
    reply = (
        f"장부 재고({part.stock}{part.unit})보다 많아요. 그래도 {action}할까요?"
        if short
        else f"{part.name}{qty} {action}할까요?"
    )
    card = Card(
        type=type_,
        entry_id=entry.id,
        expires_at=entry.expires_at,
        part_id=part.part_id,
        name=part.name,
        stock=part.stock,
        unit=part.unit,
        **common,
    )
    return reply, card


def _candidate_out(c: Candidate) -> CandidateOut:
    return CandidateOut(part_id=c.part_id, name=c.name, stock=c.stock, reason=c.reason)


def _query_reply(db: Session, parsed: Interpretation, now: datetime) -> str:
    candidates = find_candidates(db, parsed.part_text, None)
    if not candidates:
        return f"'{parsed.part_text or ''}'에 해당하는 부품을 찾지 못했어요."
    if len(candidates) > 1:
        names = ", ".join(c.name for c in candidates)
        return f"어떤 부품인지 알려 주세요: {names}"
    part = candidates[0]
    at = now.astimezone(KST).strftime("%m/%d %H:%M")
    # 입고 예정·소진 예상일은 발주·지표 계산 Issue 이후 채운다.
    return f"{part.name} 현재 재고 {part.stock}{part.unit}이에요. (계산 기준 {at})"


def handle_message(
    db: Session,
    user: TokenClaims,
    client_message_id: str,
    text: str,
    interpreter: Interpreter,
    now: datetime | None = None,
) -> MessageResponse:
    now = now or clock.utcnow()
    message_id = uuid.uuid4()
    cards: list[Card] = []
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

    if parsed is None:
        entry = _add_entry(db, user, message_id, "form", "OTHER", {"source_text": text}, now)
        intent, reply = "OTHER", FORM_REPLY
        cards.append(
            Card(type="form", entry_id=entry.id, intent="OTHER", expires_at=entry.expires_at)
        )
    elif parsed.intent in RECORD_INTENTS:
        intent = parsed.intent
        reply, card = _record_card(db, user, message_id, parsed, text, now)
        cards.append(card)
    elif parsed.intent == "QUERY":
        intent, reply = "QUERY", _query_reply(db, parsed, now)
    else:
        # PURCHASE_REQUEST·MAINTENANCE_DONE·COUNT는 검토·정비·실사 Issue에서 연결한다.
        intent, reply = parsed.intent, HELP_REPLY

    db.get(ChatMessage, message_id).reply = reply
    db.flush()
    return MessageResponse(message_id=message_id, intent=intent, reply=reply, cards=cards, ai=ai)
