"""채팅 해석 포트.

해석은 apps/ai가 맡는다(`POST /v1/chat/parse`). server는 이 인터페이스로만 해석 결과를 받고,
해석이 실패하면 오류 대신 폼 입력 카드로 대체한다(API 명세서 1-6).
ai 주소가 없으면 UnconfiguredInterpreter가 항상 실패를 알려 대체 경로로 동작한다.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Annotated, Literal, Protocol

from bjk_contracts import LlmUsage
from fastapi import Depends

from bjk_server.ai.client import AiClient, AiUnavailable, get_ai_client
from bjk_server.ai.usage import record_usage
from bjk_server.auth import CurrentUser, TenantDB

Intent = Literal["OUT", "IN", "COUNT", "QUERY", "PURCHASE_REQUEST", "MAINTENANCE_DONE", "OTHER"]
FailureReason = Literal["timeout", "error", "schema_invalid", "quota_exceeded"]


@dataclass(frozen=True)
class Interpretation:
    intent: Intent
    part_text: str | None = None
    qty: int | None = None
    equipment_text: str | None = None
    supplier_text: str | None = None
    # 원문 단위 표기("개", "박스"). 부품 기본 단위로 바꾸는 일은 server가 한다.
    unit: str | None = None
    # 원문 단가(발주 요청). 없으면 검토가 등록 단가를 쓴다.
    unit_price: int | None = None
    # 두 번째 품목부터. 같은 의도의 품목별 해석("볼트 200개, 너트 200개 씀")
    more: tuple["Interpretation", ...] = ()


class InterpreterUnavailable(Exception):
    def __init__(self, reason: FailureReason) -> None:
        super().__init__(reason)
        self.reason: FailureReason = reason


class Interpreter(Protocol):
    def interpret(self, text: str) -> Interpretation: ...


class UnconfiguredInterpreter:
    """ai 미설정 기본값. 항상 실패를 알려 폼 입력으로 대체하게 한다."""

    def interpret(self, text: str) -> Interpretation:
        raise InterpreterUnavailable("error")


class AiInterpreter:
    """ai 채팅 해석 어댑터 (docs/ai-integration.md 2장).

    품목이 여럿이면 첫 품목을 기본 필드에, 나머지를 `more`에 담는다.
    """

    def __init__(
        self, ai: AiClient, company_id: uuid.UUID, on_usage: Callable[[LlmUsage], None]
    ) -> None:
        self._ai, self._company_id, self._on_usage = ai, company_id, on_usage

    def interpret(self, text: str) -> Interpretation:
        try:
            parsed = self._ai.parse_chat(self._company_id, text)
        except AiUnavailable as exc:
            raise InterpreterUnavailable(_failure(exc.reason.value)) from None
        if parsed.usage is not None:
            self._on_usage(parsed.usage)
        if parsed.ai.fallback or parsed.intent is None:
            reason = parsed.ai.reason.value if parsed.ai.reason else "error"
            raise InterpreterUnavailable(_failure(reason))
        intent = parsed.intent.value
        items = [
            Interpretation(
                intent=intent,
                part_text=item.part_text,
                qty=item.qty,
                equipment_text=item.equipment_text,
                supplier_text=item.supplier_text,
                unit=item.unit,
                unit_price=item.unit_price,
            )
            for item in parsed.items
        ]
        if not items:
            return Interpretation(intent)
        return replace(items[0], more=tuple(items[1:]))


def _failure(reason: str) -> FailureReason:
    # verify_failed는 의견서 검증용이라 채팅 해석에서는 오지 않는다.
    return reason if reason in ("timeout", "schema_invalid", "quota_exceeded") else "error"


def get_interpreter(
    user: CurrentUser,
    db: TenantDB,
    ai: Annotated[AiClient | None, Depends(get_ai_client)],
) -> Interpreter:
    if ai is None:
        return UnconfiguredInterpreter()
    company_id = user.company_id
    return AiInterpreter(ai, company_id, lambda usage: record_usage(db, company_id, usage))
