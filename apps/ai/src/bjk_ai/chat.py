"""채팅 해석 (F-CHAT-01). 원문에서 의도와 품목 표현만 뽑는다."""

from bjk_contracts import (
    AiMeta,
    ChatIntent,
    ChatParseRequest,
    ChatParseResponse,
    FallbackReason,
    LlmPurpose,
    ParsedItem,
)
from pydantic import BaseModel

from bjk_ai.config import Settings
from bjk_ai.gateway import CallLog, LlmGateway, call_with_retry, usage_from

SYSTEM_PROMPT = """\
너는 제조 현장 부품 창고의 채팅 기록을 구조화하는 해석기다.
작업자가 보낸 한 줄을 읽고 의도(intent)와 품목(items)을 JSON으로만 답한다.

intent는 다음 중 하나다.
- OUT: 부품을 썼다, 꺼냈다 ("3호기 베어링 두 개 씀")
- IN: 부품이 들어왔다, 받았다 ("베어링 6205ZZ 10개 들어왔어요")
- COUNT: 직접 세어 본 수량을 알린다 ("세어보니 940개")
- QUERY: 재고나 입고 예정을 묻는다 ("V벨트 몇 개 있어?")
- PURCHASE_REQUEST: 사 달라고, 시켜 달라고 요청한다 ("V벨트 30개 시켜주세요, 저번 데서요")
- MAINTENANCE_DONE: 설비 정비가 끝났다고 알린다 ("3호기 정비 끝")
- OTHER: 위 어느 것도 아니다

items 규칙:
- 품목이 여럿이면 나눠 담는다. "볼트 200개, 너트 200개 씀"은 품목 2개다.
- part_text, equipment_text, supplier_text는 원문 표현을 그대로 옮긴다. 고치거나 번역하지 않는다.
- qty는 정수로 바꾼다("두 개" → 2, "열 박스" → 10). unit은 원문 단위 그대로("개", "ea", "박스").
- unit_price는 원 단위 정수로 바꾼다("1만 8천원" → 18000, "18,000원" → 18000).
- 원문에 없는 값은 null로 둔다. 추측해서 채우지 않는다.
- MAINTENANCE_DONE은 equipment_text만 담은 품목 하나로 답한다.
- OTHER면 items는 빈 배열이다.
"""


class _LlmItem(BaseModel):
    part_text: str | None = None
    qty: int | None = None
    unit: str | None = None
    equipment_text: str | None = None
    supplier_text: str | None = None
    unit_price: int | None = None
    note: str | None = None


class _LlmOutput(BaseModel):
    """Gemini 응답 스키마. 제약은 받은 뒤 계약(`ParsedItem`)으로 검증한다."""

    intent: ChatIntent
    items: list[_LlmItem]


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _to_item(item: _LlmItem) -> ParsedItem:
    return ParsedItem(
        part_text=_clean(item.part_text),
        qty=item.qty,
        unit=_clean(item.unit),
        equipment_text=_clean(item.equipment_text),
        supplier_text=_clean(item.supplier_text),
        unit_price=item.unit_price,
        note=_clean(item.note),
    )


async def parse_chat(
    request: ChatParseRequest, *, gateway: LlmGateway | None, settings: Settings
) -> ChatParseResponse:
    if gateway is None:
        return ChatParseResponse(
            intent=None, ai=AiMeta(used=False, fallback=True, reason=FallbackReason.ERROR)
        )

    async def attempt(log: CallLog) -> tuple[ChatIntent, list[ParsedItem]]:
        result = await gateway.generate_json(
            purpose=LlmPurpose.CHAT_PARSE,
            system=SYSTEM_PROMPT,
            prompt=request.text,
            schema=_LlmOutput,
            max_tokens=1024,
            attempt=log.attempts,
        )
        log.record(result)
        output = _LlmOutput.model_validate_json(result.text)
        items = [_to_item(item) for item in output.items]
        if output.intent is ChatIntent.OTHER:
            items = []
        return output.intent, items

    parsed, reason, log = await call_with_retry(
        attempt, budget_seconds=settings.chat_budget_seconds
    )
    usage = usage_from(log, purpose=LlmPurpose.CHAT_PARSE, success=parsed is not None)
    if parsed is None:
        return ChatParseResponse(intent=None, ai=AiMeta.failed(reason), usage=usage)
    intent, items = parsed
    return ChatParseResponse(intent=intent, items=items, ai=AiMeta.ok(), usage=usage)
