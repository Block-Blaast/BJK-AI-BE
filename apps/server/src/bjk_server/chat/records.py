"""확정된 입력을 원장에 기록한다. 확인 카드 확정(CHAT-03)과 폼 입력(CHAT-05)이 함께 쓴다."""

import uuid
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from bjk_server.db.models import Equipment, Movement, Part, PartAlias
from bjk_server.errors import ApiError, ErrorCode
from bjk_server.inventory import stock_of
from bjk_server.security import TokenClaims


class MovementOut(BaseModel):
    id: uuid.UUID
    type: Literal["IN", "OUT"]
    part_id: uuid.UUID
    qty: int
    equipment_id: uuid.UUID | None
    maintenance_id: uuid.UUID | None


class AliasLearned(BaseModel):
    text: str
    part_id: uuid.UUID


class Triggered(BaseModel):
    # 재고 부족 초안·장부 의심 항목은 검토·장부 검증 기능에서 채운다.
    draft_review_id: uuid.UUID | None = None
    audit_flag_id: uuid.UUID | None = None


class RecordResponse(BaseModel):
    intent: Literal["IN", "OUT"]
    movement: MovementOut
    stock_after: int
    reply: str
    alias_learned: AliasLearned | None = None
    triggered: Triggered = Triggered()


def resolve_part(db: Session, part_id: uuid.UUID | None) -> Part:
    part = db.get(Part, part_id) if part_id else None
    if part is None or part.merged_into is not None:
        raise ApiError(ErrorCode.PART_NOT_RESOLVED, "기록할 부품을 골라 주세요.")
    return part


def resolve_equipment(db: Session, equipment_id: uuid.UUID | None) -> uuid.UUID | None:
    if equipment_id is None:
        return None
    if db.get(Equipment, equipment_id) is None:
        raise ApiError(
            ErrorCode.NOT_FOUND, "설비를 찾을 수 없습니다.", {"equipment_id": str(equipment_id)}
        )
    return equipment_id


def learn_alias(db: Session, text: str | None, part: Part) -> AliasLearned | None:
    """사용자가 확정한 표현을 별칭으로 남긴다.

    같은 표현이 여러 부품에 쓰이면 모두 모호(ambiguous)로 표시해 자동 확정에서 뺀다.
    """
    if not text or not text.strip() or text.strip().lower() == part.name.lower():
        return None
    text = text.strip()
    aliases = db.scalars(select(PartAlias).where(PartAlias.text == text)).all()
    own = next((a for a in aliases if a.part_id == part.id), None)
    if own is None:
        own = PartAlias(company_id=part.company_id, part_id=part.id, text=text, confirmed_count=0)
        db.add(own)
    own.confirmed_count += 1
    others = [a for a in aliases if a.part_id != part.id]
    for alias in [own, *others]:
        alias.ambiguous = bool(others)
    return AliasLearned(text=text, part_id=part.id)


def record_movement(
    db: Session,
    user: TokenClaims,
    intent: Literal["IN", "OUT"],
    part: Part,
    qty: int,
    equipment_id: uuid.UUID | None,
    source_text: str | None,
    message_id: uuid.UUID | None = None,
) -> tuple[Movement, int, str]:
    if qty <= 0:
        raise ApiError(ErrorCode.VALIDATION_ERROR, "수량은 1 이상이어야 합니다.", {"qty": qty})
    movement = Movement(
        id=uuid.uuid4(),
        company_id=user.company_id,
        part_id=part.id,
        type=intent,
        qty=-qty if intent == "OUT" else qty,
        author_id=user.user_id,
        equipment_id=equipment_id,
        source_text=source_text,
        message_id=message_id,
    )
    db.add(movement)
    db.flush()
    stock = stock_of(db, part.id)
    action = "출고" if intent == "OUT" else "입고"
    label = "남은 재고" if intent == "OUT" else "현재 재고"
    return movement, stock, f"{action} 완료. {label} {stock}{part.unit}"


def movement_out(movement: Movement) -> MovementOut:
    return MovementOut(
        id=movement.id,
        type=movement.type,
        part_id=movement.part_id,
        qty=movement.qty,
        equipment_id=movement.equipment_id,
        maintenance_id=movement.maintenance_id,
    )
