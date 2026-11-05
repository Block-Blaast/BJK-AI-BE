"""채팅 해석 포트.

해석은 apps/ai가 맡는다(채팅 해석 ai Issue). server는 이 인터페이스로만 해석 결과를 받고,
해석이 실패하면 오류 대신 폼 입력 카드로 대체한다(API 명세서 1-6).
ai 연동 전에는 UnconfiguredInterpreter가 항상 실패를 알려 대체 경로로 동작한다.
"""

from dataclasses import dataclass
from typing import Literal, Protocol

Intent = Literal["OUT", "IN", "COUNT", "QUERY", "PURCHASE_REQUEST", "MAINTENANCE_DONE", "OTHER"]
FailureReason = Literal["timeout", "error", "schema_invalid", "quota_exceeded"]


@dataclass(frozen=True)
class Interpretation:
    intent: Intent
    part_text: str | None = None
    qty: int | None = None
    equipment_text: str | None = None
    supplier_text: str | None = None


class InterpreterUnavailable(Exception):
    def __init__(self, reason: FailureReason) -> None:
        super().__init__(reason)
        self.reason: FailureReason = reason


class Interpreter(Protocol):
    def interpret(self, text: str) -> Interpretation: ...


class UnconfiguredInterpreter:
    """ai 연동 전 기본값. 항상 실패를 알려 폼 입력으로 대체하게 한다."""

    def interpret(self, text: str) -> Interpretation:
        raise InterpreterUnavailable("error")


def get_interpreter() -> Interpreter:
    return UnconfiguredInterpreter()
