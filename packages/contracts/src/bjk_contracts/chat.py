"""채팅 해석 (F-CHAT-01, CHAT-01) server → ai 계약.

ai는 원문에서 표현만 뽑는다. 부품·설비·공급사를 실제 ID로 바꾸는 일(매칭, F-MATCH-01),
"저번 데" 같은 공급사 표현 해석, 박스 → 개 환산, 되묻기·확인 카드 판단은 server가 한다.
"""

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from bjk_contracts.common import AiMeta, LlmUsage

CHAT_TEXT_MAX_LEN = 500


class ChatIntent(StrEnum):
    """채팅 의도 (API 명세서 2장 코드값)."""

    OUT = "OUT"
    IN = "IN"
    COUNT = "COUNT"
    QUERY = "QUERY"
    PURCHASE_REQUEST = "PURCHASE_REQUEST"
    MAINTENANCE_DONE = "MAINTENANCE_DONE"
    OTHER = "OTHER"


class ChatParseRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    company_id: UUID
    text: str = Field(min_length=1, max_length=CHAT_TEXT_MAX_LEN)


class ParsedItem(BaseModel):
    """원문에서 뽑은 한 품목. 원문에 없는 값은 비워 둔다(추측해서 채우지 않음).

    - `qty`: 숫자로 바꾼 값("두 개" → 2). 없으면 None이고 server가 되묻는다.
    - `unit`: 원문 표기 그대로("개", "ea", "박스"). 정규화는 server가 한다.
    - `part_text`, `equipment_text`, `supplier_text`: 원문 표현 그대로.
    """

    model_config = ConfigDict(frozen=True)

    part_text: str | None = None
    qty: int | None = Field(default=None, ge=0)
    unit: str | None = None
    equipment_text: str | None = None
    supplier_text: str | None = None
    unit_price: int | None = Field(default=None, ge=0)
    note: str | None = None


class ChatParseResponse(BaseModel):
    """해석 결과.

    여러 품목은 `items`에 나눠 담는다("볼트 200개, 너트 200개 씀" → 2개).
    LLM이 실패하면(1회 재시도 후) `intent`는 None, `items`는 비고 `ai.fallback`이 True다.
    server는 이때 폼 입력 카드(F-CHAT-07)로 넘긴다.
    """

    model_config = ConfigDict(frozen=True)

    intent: ChatIntent | None
    items: list[ParsedItem] = Field(default_factory=list)
    ai: AiMeta
    usage: LlmUsage | None = None

    @model_validator(mode="after")
    def _empty_on_fallback(self) -> "ChatParseResponse":
        if self.ai.fallback and (self.intent is not None or self.items):
            raise ValueError("대체 경로 응답에는 해석 결과를 담지 않는다")
        if not self.ai.fallback and self.intent is None:
            raise ValueError("정상 응답에는 intent가 필요하다")
        return self
