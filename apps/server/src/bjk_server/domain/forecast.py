"""재고 추이 예측선 (화면 W-03·W-05 그래프, 결재용 PDF REV-07). 순수 함수.

월 소모량 m을 하루에 고르게 쓰는 단순 추정이다. 정비 확정 필요량은 넣지 않는다. 발주 시 선은
발주 수량이 납기(LT90) 날에 들어온다고 본다. 판정에 쓰지 않고 그래프에만 쓴다.
"""

from dataclasses import dataclass
from datetime import date, timedelta

PROJECTION_DAYS = 56  # 8주 (F-ANAL-07 경로 시뮬레이션과 같은 기간)


@dataclass(frozen=True)
class ForecastDay:
    date: date
    with_order: float
    without_order: float


def project_stock(
    start: float, monthly_use: float, order_qty: int, lead_days: int
) -> tuple[list[float], list[float]]:
    """일별 예상 재고(발주 시, 미발주 시). 0일째가 시작 재고다."""
    daily = monthly_use / 30
    without = [round(start - daily * day, 2) for day in range(PROJECTION_DAYS + 1)]
    with_order = [v + (order_qty if day >= lead_days else 0) for day, v in enumerate(without)]
    return with_order, without


def forecast_days(
    as_of: date, start: float, monthly_use: float, order_qty: int, lead_days: int
) -> list[ForecastDay]:
    with_order, without = project_stock(start, monthly_use, order_qty, lead_days)
    return [
        ForecastDay(as_of + timedelta(days=i), w, wo)
        for i, (w, wo) in enumerate(zip(with_order, without, strict=True))
    ]
