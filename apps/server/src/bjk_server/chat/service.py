"""채팅 메시지 처리: 해석 → 부품 매칭 → 확인 카드 (API 명세서 CHAT-01)."""

import uuid
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from bjk_server import clock
from bjk_server.chat.interpreter import Interpretation, Interpreter, InterpreterUnavailable
from bjk_server.chat.matching import Candidate, find_candidates, find_equipment, is_unusual_qty
from bjk_server.chat.schemas import (
    AiStatus,
    CandidateOut,
    Card,
    CardType,
    EquipmentRef,
    MessageResponse,
)
from bjk_server.clock import KST
from bjk_server.db.models import ChatEntry, ChatMessage, Equipment, PartMetrics
from bjk_server.security import TokenClaims

CARD_TTL = timedelta(minutes=10)
RECORD_INTENTS = ("OUT", "IN")
HELP_REPLY = "기록, 조회, 발주 요청을 도와드려요."
FORM_REPLY = "자동으로 해석하지 못했어요. 입력 폼으로 기록해 주세요."
# 소진일 경로 시뮬레이션 기간 (F-ANAL-07)
STOCKOUT_HORIZON_WEEKS = 8


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
    matched = find_candidates(db, parsed.part_text, equipment.id if equipment else None)
    candidates = matched.candidates
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

    if not candidates and matched.confirmed is None:
        entry = _add_entry(db, user, message_id, "unregistered", parsed.intent, payload, now)
        label = parsed.part_text or "부품"
        reply = f"'{label}'은(는) 등록되지 않은 부품이에요. 관리자에게 등록을 요청해 주세요."
        return reply, Card(
            type="unregistered", entry_id=entry.id, expires_at=entry.expires_at, **common
        )

    # 확정 조건(별칭 일치, 규격 완전 일치 후보 1개)이 아니면 후보가 하나여도 사람이 고른다.
    if matched.confirmed is None:
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

    part = matched.confirmed
    payload["part_id"] = str(part.part_id)
    unusual = parsed.qty is not None and is_unusual_qty(db, part.part_id, parsed.intent, parsed.qty)
    type_: CardType = "warning" if unusual else "confirm"
    entry = _add_entry(db, user, message_id, type_, parsed.intent, payload, now)
    action = "출고" if parsed.intent == "OUT" else "입고"
    qty = f" {parsed.qty}{part.unit}" if parsed.qty is not None else ""
    reply = (
        f"{part.name}{qty} 맞나요? 평소보다 훨씬 많아요."
        if unusual
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


def _copula(word: str) -> str:
    """받침이 있으면 '이에요', 없으면 '예요' (예: 통이에요, 개예요)."""
    last = word[-1:] if word else ""
    has_final = "가" <= last <= "힣" and (ord(last) - ord("가")) % 28 != 0
    return "이에요" if has_final else "예요"


def _query_reply(db: Session, parsed: Interpretation, now: datetime) -> str:
    matched = find_candidates(db, parsed.part_text, None)
    candidates = [matched.confirmed] if matched.confirmed else matched.candidates
    if not candidates:
        return f"'{parsed.part_text or ''}'에 해당하는 부품을 찾지 못했어요."
    if len(candidates) > 1:
        names = ", ".join(c.name for c in candidates)
        return f"어떤 부품인지 알려 주세요: {names}"
    part = candidates[0]
    at = now.astimezone(KST).strftime("%m/%d %H:%M")
    reply = f"{part.name} 현재 재고 {part.stock}{part.unit}{_copula(part.unit)}."
    # 소진 예상일은 최신 새벽 계산(part_metrics) 값이다. 입고 예정은 발주 기능 이후 채운다.
    metrics = db.execute(
        select(PartMetrics.t_out, PartMetrics.computed_at)
        .where(PartMetrics.part_id == part.part_id)
        .order_by(PartMetrics.computed_on.desc())
        .limit(1)
    ).first()
    if metrics is None:
        return f"{reply} 소진 예상일은 새벽 계산 뒤에 알려 드려요. (재고 기준 {at})"
    computed = metrics.computed_at.astimezone(KST).strftime("%m/%d %H:%M")
    if metrics.t_out is None:
        outlook = f"앞으로 {STOCKOUT_HORIZON_WEEKS}주 안에는 다 쓰지 않을 것으로 보여요."
    else:
        outlook = f"소진 예상일은 {metrics.t_out:%m/%d}이에요."
    return f"{reply} {outlook} (재고 기준 {at}, 예상 계산 {computed})"


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
