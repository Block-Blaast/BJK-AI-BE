"""외부 지표 위험도 (기능명세서 F-EXT-02)."""

from collections.abc import Collection, Sequence
from datetime import date, timedelta
from typing import Literal

import numpy as np

Level = Literal["normal", "caution", "high"]

# 3개월 = 13주. 주간 지표 기준.
WINDOW_WEEKS = 13
MAX_RISK = 4.0
# 외부 충격 시나리오 (F-EXT-03): 해상운임 위험도를 이 값으로 고정한다.
SHOCK_CODE = "FREIGHT"
SHOCK_R = 3.0


def risk_level(r: float) -> Level:
    """r < 1 정상, 1 ≤ r < 2 주의, r ≥ 2 높음."""
    if r >= 2:
        return "high"
    if r >= 1:
        return "caution"
    return "normal"


def indicator_risk(
    values: Sequence[float], window: int = WINDOW_WEEKS
) -> tuple[float | None, float]:
    """z = 최근 3개월 변화율 ÷ 과거 3개월 변화율의 표준편차, r = min(max(0, z), 4).

    부품 공급에 불리한 방향(운임 상승, 원화 약세 = 환율 상승)만 위험으로 보므로 z가 음수면 r = 0.
    과거 변화율이 2개 미만이면 z를 계산하지 않는다(r = 0).
    """
    v = np.asarray(values, dtype=float)
    if len(v) <= window:
        return None, 0.0
    changes = v[window:] / v[:-window] - 1
    current, past = changes[-1], changes[:-1]
    if len(past) < 2:
        return None, 0.0
    sd = float(past.std(ddof=1))
    z = 0.0 if sd == 0 else float(current / sd)
    return z, min(max(0.0, z), MAX_RISK)


def apply_shock(r_by_code: dict[str, float], enabled: bool) -> dict[str, float]:
    """외부 충격이 켜져 있으면 해상운임 r을 3으로 고정한 위험도. 원래 값은 바꾸지 않는다."""
    return {**r_by_code, SHOCK_CODE: SHOCK_R} if enabled else dict(r_by_code)


def extend_for_holidays(today: date, days: int, holidays: Collection[date]) -> int:
    """납기 구간에 연휴가 겹치면 겹친 일수만큼 늘린다 (F-EXT-02 6단계).

    연휴 날은 납기 일수로 세지 않는다. 늘어난 구간에 다시 걸린 연휴도 센다(긴 춘절 대비).
    같은 날짜가 여러 출처(명절·공급사 휴무)에 있어도 한 번만 센다.
    """
    off = set(holidays)
    lead = days
    while lead - sum(1 for i in range(1, lead + 1) if today + timedelta(days=i) in off) < days:
        lead += 1
    return lead
