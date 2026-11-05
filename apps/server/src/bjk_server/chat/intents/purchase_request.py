"""발주 요청(PURCHASE_REQUEST) 의도: 부품·수량·공급사 확인 카드 (F-CHAT-04, CHAT-01).

확정(CHAT-03)하면 직원 요청 검토를 만든다. 공급사 표현은 LLM이 뽑은 원문을 코드가 해석한다
(F-CHAT-01). "저번 데"처럼 최근 발주처를 가리키는 표현은
이 부품을 가장 최근에 발주한 공급사로 바꾼다.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bjk_server.chat.intents.base import IntentContext, IntentResult, equipment_ref
from bjk_server.chat.interpreter import Interpretation
from bjk_server.chat.matching import find_candidates, find_equipment
from bjk_server.chat.records import to_base_qty
from bjk_server.chat.schemas import CandidateOut, Card, SupplierResolution
from bjk_server.db.models import Part, PurchaseOrder, Supplier, SupplierPart

# 최근 발주처를 가리키는 표현 (F-CHAT-01 "저번 데"·"늘 사던 곳")
LAST_ORDER_WORDS = ("저번", "지난번", "전에", "늘", "항상", "사던", "하던", "원래")


def handle(ctx: IntentContext, parsed: Interpretation) -> IntentResult:
    db = ctx.db
    matched = find_candidates(db, parsed.part_text, None, ctx.embedder)
    if matched.confirmed is None and not matched.candidates:
        label = parsed.part_text or "부품"
        return IntentResult(
            f"'{label}'은(는) 등록되지 않은 부품이에요. 관리자에게 등록을 요청해 주세요."
        )
    payload = {
        "part_text": parsed.part_text,
        "qty": parsed.qty,
        "unit": parsed.unit,
        "unit_price": parsed.unit_price,
        "supplier_text": parsed.supplier_text,
        "source_text": ctx.text,
    }
    common = {
        "intent": "PURCHASE_REQUEST",
        "part_text": parsed.part_text,
        "qty": parsed.qty,
        "equipment": equipment_ref(find_equipment(db, parsed.equipment_text)),
        "unit_price": parsed.unit_price,
    }
    if matched.confirmed is None:
        candidates = matched.candidates
        payload["candidate_ids"] = [str(c.part_id) for c in candidates]
        entry = ctx.add_entry("select", "PURCHASE_REQUEST", payload)
        card = Card(
            type="select",
            entry_id=entry.id,
            expires_at=entry.expires_at,
            candidates=[
                CandidateOut(part_id=c.part_id, name=c.name, stock=c.stock, reason=c.reason)
                for c in candidates
            ],
            **common,
        )
        return IntentResult(f"어떤 {parsed.part_text}을(를) 요청하시나요?", [card])

    part = matched.confirmed
    qty = to_base_qty(parsed.qty, parsed.unit, part.pack_qty)
    resolution = resolve_supplier(db, db.get(Part, part.part_id), parsed.supplier_text)
    payload.update(
        part_id=str(part.part_id),
        qty=qty,
        unit=None,
        supplier_id=str(resolution.supplier_id) if resolution.supplier_id else None,
    )
    common["qty"] = qty
    entry = ctx.add_entry("confirm", "PURCHASE_REQUEST", payload)
    card = Card(
        type="confirm",
        entry_id=entry.id,
        expires_at=entry.expires_at,
        part_id=part.part_id,
        name=part.name,
        stock=part.stock,
        unit=part.unit,
        supplier_resolution=resolution,
        **common,
    )
    qty_text = f" {qty}{part.unit}" if qty is not None else ""
    to = f", {resolution.name}로" if resolution.name else ""
    return IntentResult(f"{part.name}{qty_text}{to} 요청하셨나요?", [card])


def resolve_supplier(db: Session, part: Part, text: str | None) -> SupplierResolution:
    """공급사 표현 → 공급사 (API 명세서 CHAT-01 `supplier_resolution`).

    이름 일치(named), 최근 발주처 표현은 최근 발주 공급사(last_order), 이력이 없거나 표현이 없으면
    기본 공급사(default), 그것도 없으면 none.
    """
    last_order = bool(text) and any(word in text for word in LAST_ORDER_WORDS)
    if last_order:
        recent = _last_ordered(db, part.id)
        if recent is not None:
            return SupplierResolution(
                text=text, supplier_id=recent.id, name=recent.name, method="last_order"
            )
    elif text:
        named = _named(db, part.id, text)
        if named is not None:
            return SupplierResolution(
                text=text, supplier_id=named.id, name=named.name, method="named"
            )
        return SupplierResolution(text=text, method="none")
    default = db.get(Supplier, part.default_supplier_id) if part.default_supplier_id else None
    if default is None:
        return SupplierResolution(text=text, method="none")
    return SupplierResolution(
        text=text, supplier_id=default.id, name=default.name, method="default"
    )


def _last_ordered(db: Session, part_id: uuid.UUID) -> Supplier | None:
    """이 부품을 가장 최근에 발주한 공급사. 취소한 발주는 뺀다."""
    supplier_id = db.scalar(
        select(PurchaseOrder.supplier_id)
        .where(PurchaseOrder.part_id == part_id, PurchaseOrder.status != "cancelled")
        .order_by(PurchaseOrder.approved_at.desc(), PurchaseOrder.id.desc())
        .limit(1)
    )
    return db.get(Supplier, supplier_id) if supplier_id else None


def _named(db: Session, part_id: uuid.UUID, text: str) -> Supplier | None:
    """이름이 표현을 포함하거나 표현이 이름을 포함하는 공급사. 이 부품을 파는 곳을 먼저 본다."""
    key = text.replace(" ", "").lower()
    if not key:
        return None
    sells = select(SupplierPart.supplier_id).where(SupplierPart.part_id == part_id)
    name = func.lower(func.replace(Supplier.name, " ", ""))
    return db.scalar(
        select(Supplier)
        .where((name.contains(key)) | (func.strpos(key, name) > 0))
        .order_by(Supplier.id.in_(sells).desc(), Supplier.name)
        .limit(1)
    )
