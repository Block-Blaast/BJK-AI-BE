"""발주 검토 의견서 문장 (F-REVIEW-08) server → ai 계약.

server가 판정·체크·수정안을 다 만든 뒤 문장만 맡긴다. 숫자 검증(허용 목록 대조·판정 일치·누락)은
server가 하고, 실패하면 `feedback`에 틀린 항목을 담아 다시 부른다(최대 2회). 그래도 실패하거나
ai가 대체 응답을 주면 server는 정해진 양식 의견서를 쓴다.
"""

from datetime import date, datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from bjk_contracts.common import AiMeta, LlmUsage


class Verdict(StrEnum):
    OK = "ok"
    REVISE = "revise"
    HOLD = "hold"


class Flag(StrEnum):
    URGENT = "urgent"
    CAUTION = "caution"
    ALTERNATIVE = "alternative"


class CheckCode(StrEnum):
    C01 = "C-01"
    C02 = "C-02"
    C03 = "C-03"
    C04 = "C-04"
    C05 = "C-05"
    C06 = "C-06"
    C07 = "C-07"
    C08 = "C-08"
    C09 = "C-09"


class CheckLevel(StrEnum):
    WARNING = "warning"
    URGENT = "urgent"
    INFO = "info"


class HoldReason(StrEnum):
    PART_UNRESOLVED = "part_unresolved"
    SUPPLIER_UNRESOLVED = "supplier_unresolved"
    NO_DEMAND_DATA = "no_demand_data"


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class CheckFacts(_Frozen):
    """걸린 체크 하나와 그 근거 숫자. `facts`는 REV-02 `checks[].facts`와 같다."""

    code: CheckCode
    level: CheckLevel
    facts: dict[str, int | float | str | None] = Field(default_factory=dict)


class OrderLine(_Frozen):
    qty: int = Field(ge=0)
    supplier_name: str | None = None
    unit_price: int | None = Field(default=None, ge=0)
    total: int | None = Field(default=None, ge=0)


class Proposal(OrderLine):
    """수정안. `saving`이 음수면 수량을 늘려 생기는 추가 비용이다(F-REVIEW-05 4번)."""

    saving: int = 0
    no_order: bool = False
    basis: list[CheckCode] = Field(default_factory=list)


class Alternative(_Frozen):
    """판정을 바꾸지 않는 대안. 더 싼 공급사(C-06) 또는 다음 단가 구간."""

    kind: Literal["cheaper_supplier", "price_tier"]
    supplier_name: str | None = None
    qty: int = Field(ge=0)
    unit_price: int = Field(ge=0)
    total: int = Field(ge=0)
    saving: int


class Risk(_Frozen):
    stockout_date: date | None = None
    equipment: list[str] = Field(default_factory=list)
    loss: int = Field(default=0, ge=0)
    is_estimate: bool = False


class OpinionRequest(_Frozen):
    company_id: UUID
    part_name: str = Field(min_length=1)
    verdict: Verdict
    flags: list[Flag] = Field(default_factory=list)
    hold_reasons: list[HoldReason] = Field(default_factory=list)
    checks: list[CheckFacts] = Field(default_factory=list)
    original: OrderLine
    proposal: Proposal | None = None
    alternatives: list[Alternative] = Field(default_factory=list)
    risk_if_not_ordered: Risk = Field(default_factory=Risk)
    data_mode: Literal["statistical", "estimated"] = "statistical"
    computed_at: datetime

    # 재작성 요청일 때만 채운다. server 검증이 찾은 틀린 항목과 그때의 의견서.
    previous_text: str | None = None
    feedback: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _feedback_needs_previous(self) -> "OpinionRequest":
        if self.feedback and not self.previous_text:
            raise ValueError("feedback이 있으면 previous_text가 필요하다")
        return self


class OpinionResponse(_Frozen):
    """의견서 전문. 구성 순서는 F-REVIEW-08을 따른다.

    첫 줄의 판정 표시(`[수정 권고]` 등)와 마지막 줄의 계산 기준 시각은 ai가 입력값으로 직접 쓴다.
    실패하면 `text`는 None이고 `ai.fallback`이 True다.
    """

    text: str | None
    ai: AiMeta
    usage: LlmUsage | None = None

    @model_validator(mode="after")
    def _text_matches_fallback(self) -> "OpinionResponse":
        if self.ai.fallback != (self.text is None):
            raise ValueError("대체 경로면 text가 비고, 정상 응답이면 text가 있어야 한다")
        return self
