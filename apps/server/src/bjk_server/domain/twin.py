"""3D 창고 예측 (화면 W-11, 명세 밖, #281). 순수 함수, 난수·LLM 없음.

부품마다 8주 동안 날짜별 재고(중앙값 경로)와 그날부터 다음 발주분이 들어올 때까지의 결품 확률을
구한다. 프론트 목업(`mocks/fixtures/simulate.ts`)과 같은 식이라 목업에서 서버로 바꿔도 그림이
같은 규칙으로 바뀐다. 결품 확률은 기간 수요를 정규분포로 근사한 값이고, 검토·새벽 계산의 경로
시뮬레이션(F-ANAL-07)과는 별개다.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

HORIZON_DAYS = 56  # 8주
RISK_P_OUT = 0.3  # 결품 확률 30% 이상이면 위험 (놓친 발주 기준과 같다)
REVIEW_PERIOD_DAYS = 7  # 다음 발주분이 들어올 때까지 늦을 때 납기에 더하는 발주 주기
# 기간 수요의 변동계수. 수요가 들쭉날쭉할수록 크게 잡는다.
PATTERN_CV = {"smooth": 0.25, "erratic": 0.6, "intermittent": 0.8, "lumpy": 1.2}
DEFAULT_CV = 1.0  # insufficient, 계산 전

BinStatus = Literal["normal", "low", "risk", "out"]
EquipmentStatus = Literal["normal", "warn", "down"]


@dataclass(frozen=True)
class BinInput:
    stock: float
    daily: float  # 하루 평균 소모 = 월 소모량 m ÷ 30
    cv: float
    lt90: int
    reorder_point: int | None
    arrivals: Sequence[tuple[date, int]]  # (도착일, 수량)
    maintenance: Sequence[tuple[date, int]]  # (예정일, 확정 필요량)


@dataclass(frozen=True)
class BinPath:
    qty: list[float]
    status: list[BinStatus]
    p_out: list[float]


def _phi(z: float) -> float:
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def _sum_between(items: Sequence[tuple[date, int]], after: date, until: date) -> int:
    """after < 날짜 ≤ until 인 수량 합."""
    return sum(q for d, q in items if after < d <= until)


def _p_out(b: BinInput, day: date, qty: float) -> float:
    window = b.lt90 + REVIEW_PERIOD_DAYS
    until = day + timedelta(days=window)
    demand = b.daily * window + _sum_between(b.maintenance, day, until)
    if demand <= 0:
        return 0.01
    supply = max(0.0, qty) + _sum_between(b.arrivals, day, until)
    sd = max(demand * b.cv, 0.5)
    p = 1 - _phi((supply - demand) / sd)
    return round(min(0.99, max(0.01, p)), 2)


def project_bin(b: BinInput, base: date, horizon: int = HORIZON_DAYS) -> BinPath:
    """0일(기준일 현재)부터 horizon일까지의 저녁 재고·상태·결품 확률."""
    before = base - timedelta(days=1)
    consumes = b.daily > 0 or bool(b.maintenance)
    qty: list[float] = []
    status: list[BinStatus] = []
    p_out: list[float] = []
    for d in range(horizon + 1):
        day = base + timedelta(days=d)
        q = round(
            b.stock
            + _sum_between(b.arrivals, before, day)
            - b.daily * d
            - _sum_between(b.maintenance, before, day),
            1,
        )
        p = _p_out(b, day, q) if consumes else 0.0
        if consumes and q <= 0:
            s: BinStatus = "out"
        elif p >= RISK_P_OUT:
            s = "risk"
        elif b.reorder_point is not None and q <= b.reorder_point:
            s = "low"
        else:
            s = "normal"
        qty.append(max(0.0, q))
        status.append(s)
        p_out.append(p)
    return BinPath(qty, status, p_out)


@dataclass(frozen=True)
class EquipmentDay:
    status: EquipmentStatus
    loss: int | None
    causes: list[str]


def project_equipment(
    part_ids: Sequence[str],
    bins: dict[str, BinPath],
    lt50: dict[str, int],
    daily_loss: int,
    horizon: int = HORIZON_DAYS,
) -> list[EquipmentDay]:
    """설비가 쓰는 부품 중 하나라도 바닥나면 멈춤, 위험하면 주의.

    멈추는 날의 손실 L = 하루 손실(시간당 손실 × 가동 시간) × 바닥난 부품 중 가장 긴 보통 납기
    (F-ANAL-08). 시간당 손실이 없으면 null.
    """
    used = [p for p in part_ids if p in bins]
    days: list[EquipmentDay] = []
    for d in range(horizon + 1):
        out = [p for p in used if bins[p].status[d] == "out"]
        risk = [p for p in used if bins[p].status[d] == "risk"]
        lead = max((lt50.get(p, 7) for p in out), default=0)
        days.append(
            EquipmentDay(
                status="down" if out else "warn" if risk else "normal",
                loss=daily_loss * lead if out and daily_loss > 0 else None,
                causes=out or risk,
            )
        )
    return days
