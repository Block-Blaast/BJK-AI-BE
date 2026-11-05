"""출고·입고(OUT·IN) 의도: 부품 매칭 → 확인 카드 (API 명세서 CHAT-01)."""

from bjk_server.chat.intents.base import IntentContext, IntentResult, equipment_ref
from bjk_server.chat.interpreter import Interpretation
from bjk_server.chat.matching import Candidate, find_candidates, find_equipment, is_unusual_qty
from bjk_server.chat.records import to_base_qty
from bjk_server.chat.schemas import CandidateOut, Card, CardType


def handle(ctx: IntentContext, parsed: Interpretation) -> IntentResult:
    """출고·입고 메시지의 확인 카드와 답변. 여러 품목이면 품목마다 카드 하나, 답변은 줄로 잇는다."""
    results = [_item(ctx, item) for item in (parsed, *parsed.more)]
    if len(results) == 1:
        return results[0]
    reply = "\n".join(r.reply for r in results)
    return IntentResult(reply, [card for r in results for card in r.cards])


def _item(ctx: IntentContext, parsed: Interpretation) -> IntentResult:
    db = ctx.db
    equipment = find_equipment(db, parsed.equipment_text)
    matched = find_candidates(
        db, parsed.part_text, equipment.id if equipment else None, ctx.embedder
    )
    candidates = matched.candidates
    common = {
        "intent": parsed.intent,
        "part_text": parsed.part_text,
        "qty": parsed.qty,
        "equipment": equipment_ref(equipment),
    }
    # 부품을 고르기 전에는 원문 단위를 남겨 두고 확정할 때 그 부품의 입수량으로 바꾼다.
    payload = {
        "part_text": parsed.part_text,
        "qty": parsed.qty,
        "unit": parsed.unit,
        "equipment_id": str(equipment.id) if equipment else None,
        "source_text": ctx.text,
    }

    if not candidates and matched.confirmed is None:
        entry = ctx.add_entry("unregistered", parsed.intent, payload)
        label = parsed.part_text or "부품"
        reply = f"'{label}'은(는) 등록되지 않은 부품이에요. 관리자에게 등록을 요청해 주세요."
        card = Card(type="unregistered", entry_id=entry.id, expires_at=entry.expires_at, **common)
        return IntentResult(reply, [card])

    # 확정 조건(별칭 일치, 규격 완전 일치 후보 1개, 코사인 확정)이 아니면 후보가 하나여도
    # 사람이 고른다.
    if matched.confirmed is None:
        payload["candidate_ids"] = [str(c.part_id) for c in candidates]
        entry = ctx.add_entry("select", parsed.intent, payload)
        card = Card(
            type="select",
            entry_id=entry.id,
            expires_at=entry.expires_at,
            candidates=[_candidate_out(c) for c in candidates],
            **common,
        )
        return IntentResult(f"어떤 {parsed.part_text}인가요?", [card])

    part = matched.confirmed
    base_qty = to_base_qty(parsed.qty, parsed.unit, part.pack_qty)
    payload.update(part_id=str(part.part_id), qty=base_qty, unit=None)
    common["qty"] = base_qty
    unusual = base_qty is not None and is_unusual_qty(db, part.part_id, parsed.intent, base_qty)
    type_: CardType = "warning" if unusual else "confirm"
    entry = ctx.add_entry(type_, parsed.intent, payload)
    action = "출고" if parsed.intent == "OUT" else "입고"
    qty = f" {base_qty}{part.unit}" if base_qty is not None else ""
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
    return IntentResult(reply, [card])


def _candidate_out(c: Candidate) -> CandidateOut:
    return CandidateOut(part_id=c.part_id, name=c.name, stock=c.stock, reason=c.reason)
