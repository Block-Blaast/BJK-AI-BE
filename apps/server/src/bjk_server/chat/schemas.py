"""채팅 API 요청·응답 스키마 (API 명세서 CHAT)."""

import uuid
from datetime import date, datetime
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


class MaintenanceRef(BaseModel):
    id: uuid.UUID
    scheduled_date: date


class SupplierResolution(BaseModel):
    """발주 요청의 공급사 표현 해석 (CHAT-01). method: last_order·default·named·none."""

    text: str | None = None
    supplier_id: uuid.UUID | None = None
    name: str | None = None
    method: Literal["last_order", "default", "named", "none"]


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
    # IN confirm·warning: 열린 발주와 대조 미리 보기(complete·partial·mismatch·no_order)
    po_match: Literal["complete", "partial", "mismatch", "no_order"] | None = None
    # PURCHASE_REQUEST: 요청 단가와 공급사 해석
    unit_price: int | None = None
    supplier_resolution: SupplierResolution | None = None
    # MAINTENANCE_DONE confirm: 완료할 정비
    maintenance: MaintenanceRef | None = None
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
    # COUNT 응답에서 차이 사유를 보낼 실사 요청(AUD-04). 그 밖에는 null
    count_request_id: uuid.UUID | None = None
