"""부품 근거 지표 계산 (기능명세서 F-ANAL). LLM을 쓰지 않는 순수 함수.

수요는 주 단위(오래된 주 → 최근 주) 배열로 받는다. 정비에 연결된 출고는 호출 쪽에서 미리 뺀다
(F-ANAL-03, 정비 확정 필요량 F와의 이중 계산 방지).
"""

import hashlib
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal

import numpy as np

DemandClass = Literal["smooth", "erratic", "intermittent", "lumpy", "insufficient"]
Abc = Literal["A", "B", "C"]

MIN_WEEKS = 8
ADI_CUT, CV2_CUT = 1.32, 0.49
ALPHA = 0.1
BOOTSTRAP = 10_000
PATH_WEEKS = 8


def seed_for(company_id: object, part_id: object, day: date) -> int:
    """재현성: 난수 시드 = hash(회사, 부품, 날짜)."""
    digest = hashlib.sha256(f"{company_id}:{part_id}:{day.isoformat()}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def abc_classes(usage: Mapping[object, float]) -> dict[object, Abc]:
    """최근 12개월 사용 금액(또는 사용량) 누적 비율 80% A, 95% B, 나머지 C (F-ANAL-01)."""
    total = sum(usage.values())
    if total <= 0:
        return dict.fromkeys(usage, "C")
    result: dict[object, Abc] = {}
    cumulative = 0.0
    for key, value in sorted(usage.items(), key=lambda kv: (-kv[1], str(kv[0]))):
        # 이 부품을 더하기 전 누적 비율로 등급을 정해, 1위 부품은 항상 A가 된다.
        share = cumulative / total
        result[key] = "A" if share < 0.80 else "B" if share < 0.95 else "C"
        cumulative += value
    return result


def classify(weekly: Sequence[float]) -> DemandClass:
    """ADI·CV² 기준 1.32 / 0.49 (F-ANAL-02). 8주 미만은 insufficient."""
    w = np.asarray(weekly, dtype=float)
    if len(w) < MIN_WEEKS:
        return "insufficient"
    sizes = w[w > 0]
    if len(sizes) == 0:
        return "intermittent"
    adi = len(w) / len(sizes)
    cv2 = float((sizes.std() / sizes.mean()) ** 2)
    if adi < ADI_CUT:
        return "smooth" if cv2 < CV2_CUT else "erratic"
    return "intermittent" if cv2 < CV2_CUT else "lumpy"


def forecast_weekly(
    weekly: Sequence[float], demand_class: DemandClass, alpha: float = ALPHA
) -> float:
    """smooth·erratic은 단순 지수평활, intermittent·lumpy는 SBA (F-ANAL-03)."""
    w = np.asarray(weekly, dtype=float)
    if len(w) == 0:
        return 0.0
    if demand_class in ("smooth", "erratic"):
        level = w[0]
        for x in w[1:]:
            level = alpha * x + (1 - alpha) * level
        return float(level)

    nonzero = np.flatnonzero(w > 0)
    if len(nonzero) == 0:
        return 0.0
    z = w[nonzero[0]]
    p = float(nonzero[0] + 1)
    since = 0
    for x in w[nonzero[0] + 1 :]:
        since += 1
        if x > 0:
            z = alpha * x + (1 - alpha) * z
            p = alpha * since + (1 - alpha) * p
            since = 0
    return float((1 - alpha / 2) * z / p)


def bootstrap_demand(
    weekly: Sequence[float], days: float, rng: np.random.Generator, n: int = BOOTSTRAP
) -> np.ndarray:
    """과거 주간 수요를 복원 추출해 days일 동안의 통계 수요 분포를 만든다 (F-ANAL-05)."""
    w = np.asarray(weekly, dtype=float)
    weeks = days / 7
    if len(w) == 0 or weeks <= 0:
        return np.zeros(n)
    k = max(1, math.ceil(weeks))
    return rng.choice(w, size=(n, k)).sum(axis=1) * (weeks / k)


def poisson_demand(
    monthly_estimate: float | None, days: float, rng: np.random.Generator, n: int = BOOTSTRAP
) -> np.ndarray:
    """데이터 부족(8주 미만): 포아송(λ = 월 사용 추정치 × T일 ÷ 30). 추정치가 없으면 0."""
    if not monthly_estimate:
        return np.zeros(n)
    return rng.poisson(monthly_estimate * days / 30, size=n).astype(float)


def upper_quantile(samples: np.ndarray, q: float, fixed: float = 0.0) -> int:
    """분포의 상위 분위수 + 확정 필요량, 개수 단위로 올림."""
    return math.ceil(float(np.quantile(samples, q)) + fixed - 1e-9)


@dataclass(frozen=True)
class PathResult:
    t_out_day: int | None  # 재고 0 도달일 중앙값 (오늘부터 며칠 뒤), 8주 안에 없으면 None
    p_out: float  # 다음 입고 가능일까지 결품 확률


def simulate_paths(
    stock: float,
    weekly_samples: np.ndarray,
    maintenance: Sequence[tuple[int, float]],
    arrival_day: int,
    rng: np.random.Generator,
    n: int = BOOTSTRAP,
) -> PathResult:
    """8주 경로 시뮬레이션 (F-ANAL-07).

    주마다 weekly_samples에서 수요를 뽑아 그 주 마지막 날에 빼고, 정비 확정 필요량은 예정일에 뺀다.
    재고가 0 이하가 되는 첫날을 경로별 소진일로 본다.
    """
    days = PATH_WEEKS * 7
    daily = np.zeros((n, days))
    if len(weekly_samples):
        daily[:, 6::7] = rng.choice(weekly_samples, size=(n, PATH_WEEKS))
    for day, qty in maintenance:
        if 0 <= day < days:
            daily[:, day] += qty
    remaining = stock - np.cumsum(daily, axis=1)
    hit = remaining <= 0
    first = np.where(hit.any(axis=1), hit.argmax(axis=1), np.inf)
    if stock <= 0:
        first[:] = 0
    median = float(np.median(first))
    t_out = None if math.isinf(median) else int(median)
    return PathResult(t_out_day=t_out, p_out=float(np.mean(first <= arrival_day)))


def round_up_moq(qty: float, moq: int | None) -> int:
    """권장 발주량을 MOQ 배수로 올림. 0이면 0."""
    if qty <= 0:
        return 0
    unit = max(1, moq or 1)
    return math.ceil(qty / unit - 1e-9) * unit


def recommended_qty(
    d95: float, stock: float, incoming: float, hidden_confirmed: float, moq: int | None
) -> int:
    """R = max(0, D95 − S − O − H_c) → MOQ 올림 (F-ANAL-09). 검토 시에는 P도 뺀다."""
    return round_up_moq(max(0.0, d95 - stock - incoming - hidden_confirmed), moq)


def expected_loss(equipment: Sequence[tuple[int, int]], lt50_days: float) -> int:
    """L = Σ(시간당 손실 × 하루 가동 시간) × LT50 (F-ANAL-08)."""
    return int(round(sum(loss * hours for loss, hours in equipment) * lt50_days))
