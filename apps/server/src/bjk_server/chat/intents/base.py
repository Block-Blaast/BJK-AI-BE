"""의도 처리기 공통 입력·결과와 확인 카드 저장."""

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from bjk_server.chat.interpreter import Interpretation
from bjk_server.chat.matching import QueryEmbedder
from bjk_server.chat.schemas import Card, CardType, EquipmentRef
from bjk_server.db.models import ChatEntry, Equipment
from bjk_server.security import TokenClaims

CARD_TTL = timedelta(minutes=10)


@dataclass(frozen=True)
class IntentContext:
    db: Session
    user: TokenClaims
    message_id: uuid.UUID
    text: str
    now: datetime
    embedder: QueryEmbedder | None = None

    def add_entry(self, type_: CardType, intent: str, payload: dict) -> ChatEntry:
        entry = ChatEntry(
            id=uuid.uuid4(),
            company_id=self.user.company_id,
            message_id=self.message_id,
            user_id=self.user.user_id,
            type=type_,
            intent=intent,
            payload=payload,
            expires_at=self.now + CARD_TTL,
        )
        self.db.add(entry)
        return entry


@dataclass
class IntentResult:
    reply: str
    cards: list[Card] = field(default_factory=list)
    # COUNT: 차이 사유(AUD-04)를 받을 실사 요청
    count_request_id: uuid.UUID | None = None


IntentHandler = Callable[[IntentContext, Interpretation], IntentResult]


def equipment_ref(equipment: Equipment | None) -> EquipmentRef | None:
    return EquipmentRef(id=equipment.id, name=equipment.name) if equipment else None
