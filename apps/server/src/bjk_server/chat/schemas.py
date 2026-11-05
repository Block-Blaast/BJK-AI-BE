"""채팅 API 요청·응답 스키마 (API 명세서 CHAT)."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from bjk_server.chat.interpreter import FailureReason, Intent

CardType = Literal["confirm", "select", "warning", "unregistered", "form"]


class AiStatus(BaseModel):
    used: bool
    fallback: bool
    reason: FailureReason | None = None


class EquipmentRef(BaseModel):
    id: uuid.UUID
    name: str


class CandidateOut(BaseModel):
    part_id: uuid.UUID
    name: str
    stock: int
    reason: Literal["alias", "equipment_part", "name", "semantic"]


class Card(BaseModel):
    type: CardType
    entry_id: uuid.UUID
    intent: Intent
    part_text: str | None = None
    qty: int | None = None
    equipment: EquipmentRef | None = None
    # confirm·warning: 확정 대상 부품
    part_id: uuid.UUID | None = None
    name: str | None = None
    stock: int | None = None
    unit: str | None = None
    # select: 고를 후보
    candidates: list[CandidateOut] = Field(default_factory=list)
    expires_at: datetime


class MessageRequest(BaseModel):
    client_message_id: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1, max_length=500)


class MessageResponse(BaseModel):
    message_id: uuid.UUID
    intent: Intent
    reply: str
    cards: list[Card]
    ai: AiStatus
