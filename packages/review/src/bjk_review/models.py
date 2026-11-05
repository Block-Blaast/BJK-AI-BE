"""검토 입력(스냅샷·요청·설정값)과 결과.

스냅샷은 server가 DB에서 모아 고정한 값이다(F-REVIEW-02). 엔진은 이 값만 보고 계산하므로
같은 스냅샷·요청·설정값이면 언제 돌려도 같은 결과가 나온다. "오늘"도 스냅샷의 `as_of`를 쓴다.
"""

from datetime import date, datetime
from typing import Literal

from bjk_contracts import CheckCode, CheckLevel, Flag, HoldReason, Verdict
from pydantic import BaseModel, ConfigDict, Field


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class PriceTier(_Frozen):
    """`supplier_parts.price_tiers` 한 줄. `min_qty` 이상 사면 `unit_price`."""

    min_qty: int = Field(ge=1)
    unit_price: int = Field(ge=0)


class SupplierOffer(_Frozen):
    """이 부품을 파는 공급사 하나의 조건. `lt90`은 외부 요인·휴무일을 반영한 공급사별 값."""

    supplier_id: str
    name: str
    unit_price: int = Field(ge=0)
    moq: int = Field(default=1, ge=1)
    price_tiers: list[PriceTier] = Field(default_factory=list)
    shipping_fee: int = Field(default=0, ge=0)
    lt90: int = Field(ge=0)


class OpenOrder(_Frozen):
    """같은 부품(병합·같은 규격 포함)의 열린 발주."""

    qty: int = Field(ge=0)
    eta: date | None = None


class OpenRequest(_Frozen):
    """같은 부품의 다른 열린 요청. 수정안이 있으면 수정안 수량."""

    review_id: str
    qty: int = Field(ge=0)


class HiddenStock(_Frozen):
    """같은 규격으로 등록된 다른 부품의 재고. 30일 안 실사이고 의심이 아니면 `confirmed`."""

    part_id: str
    name: str
    qty: int = Field(ge=0)
    confirmed: bool


class PriceStats(_Frozen):
    """최근 구매 단가 통계. `n == 0`이면 C-05를 건너뛴다."""

    mean: float | None = None
    sigma: float = 0.0
    n: int = Field(default=0, ge=0)


class ReviewSnapshot(_Frozen):
    as_of: date
    computed_at: datetime

    part_id: str | None
    part_name: str | None = None

    stock: int  # S, 병합 부품 포함
    incoming: int = Field(default=0, ge=0)  # O, 필요 시점 전 도착분
    open_orders: list[OpenOrder] = Field(default_factory=list)
    open_requests: list[OpenRequest] = Field(default_factory=list)  # P의 출처
    hidden: list[HiddenStock] = Field(default_factory=list)  # H_c, H_u의 출처

    m: float = Field(default=0.0, ge=0)  # 월 소모량(정비 출고 제외)
    f_period: int = Field(default=0, ge=0)  # F, 대비 기간 확정 필요량
    f_12m: int = Field(default=0, ge=0)  # 향후 12개월 확정 필요량
    d95: int = Field(ge=0)
    d99: int = Field(ge=0)
    t_out: date | None = None  # 소진 예상일 = 필요 시점 t_need
    t_deadline: date | None = None  # t_out − 기본 공급사 LT90

    default_supplier_id: str | None = None
    suppliers: list[SupplierOffer] = Field(default_factory=list)
    price_stats: PriceStats = Field(default_factory=PriceStats)

    import_dependent: bool = False
    r_lead: float = Field(default=0.0, ge=0)
    r_price: float = Field(default=0.0, ge=0)
    holidays_in_lead: list[str] = Field(default_factory=list)

    loss: int = Field(default=0, ge=0)  # L
    loss_equipment: list[str] = Field(default_factory=list)
    loss_is_estimate: bool = False
    data_mode: Literal["statistical", "estimated"] = "statistical"

    # 보류 판단(F-REVIEW-03)
    has_usage_history: bool = True
    has_maintenance_plan: bool = False
    has_usage_estimate: bool = False

    @property
    def hidden_confirmed(self) -> int:
        return sum(h.qty for h in self.hidden if h.confirmed)

    @property
    def hidden_unconfirmed(self) -> int:
        return sum(h.qty for h in self.hidden if not h.confirmed)

    @property
    def other_requests(self) -> int:
        return sum(r.qty for r in self.open_requests)

    def offer(self, supplier_id: str | None) -> SupplierOffer | None:
        return next((s for s in self.suppliers if s.supplier_id == supplier_id), None)


class OrderRequest(_Frozen):
    """원안. 시스템 초안은 공급사·단가가 비어 있을 수 있다(기본 공급사·등록 단가 사용)."""

    qty: int = Field(ge=0)
    supplier_id: str | None = None
    unit_price: int | None = Field(default=None, ge=0)


class ReviewSettings(_Frozen):
    """검토 기준값 (API 명세서 SYS-01). 스냅샷과 함께 저장해 판정을 재현한다."""

    c02_months: float = 12
    c05_sigma: float = 2
    c05_min_ratio: float = 1.05
    c05_small_n_ratio: float = 1.15
    c06_ratio: float = 0.9
    c08_days: int = 5
    # 단가 구간 대안: 다음 구간까지 올려도 총액 증가가 이 비율 이내면 제시(F-REVIEW-05 3번)
    tier_max_increase: float = 0.05


class Check(_Frozen):
    code: CheckCode
    level: CheckLevel
    facts: dict[str, int | float | str | None] = Field(default_factory=dict)


class Line(_Frozen):
    qty: int
    supplier_id: str | None
    supplier_name: str | None
    unit_price: int | None
    total: int


class ProposalLine(Line):
    saving: int  # 원안 총액 − 수정안 총액. 음수면 추가 비용
    no_order: bool
    basis: list[CheckCode]


class AlternativeLine(Line):
    id: str
    kind: Literal["cheaper_supplier", "price_tier"]
    saving: int  # 수정안 총액 − 대안 총액


class RiskIfNotOrdered(_Frozen):
    stockout_date: date | None
    equipment: list[str]
    loss: int
    is_estimate: bool


class CountRequest(_Frozen):
    """미확인 숨은 재고 실사 요청 대상. 블라인드 실사라 장부 수량은 담지 않는다."""

    part_id: str
    name: str


class ReviewResult(_Frozen):
    verdict: Verdict
    flags: list[Flag]
    hold_reasons: list[HoldReason]
    checks: list[Check]
    original: Line
    proposal: ProposalLine | None
    alternatives: list[AlternativeLine]
    risk_if_not_ordered: RiskIfNotOrdered
    count_requests: list[CountRequest]
    review_hash: str
