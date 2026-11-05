"""장부 검증 규칙 5종 (기능명세서 F-AUDIT-01~05). 순수 함수.

규칙마다 걸린 근거(evidence)와 중복 판단 키(key)를 돌려준다. 키가 사건(정비·원장 행)을 가리키면
그 사건은 한 번만 의심 항목이 되고, 규칙 이름만이면 닫힌 뒤 억제 기간이 지나야 다시 뜬다.
"""

import math
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Literal

Rule = Literal[
    "NEGATIVE_STOCK",
    "MAINTENANCE_OUT_MISMATCH",
    "PATTERN_DEVIATION",
    "SPIKE",
    "COUNT_OVERDUE",
]
Level = Literal["high", "medium", "low"]

LEVEL: dict[str, Level] = {
    "NEGATIVE_STOCK": "high",
    "MAINTENANCE_OUT_MISMATCH": "high",
    "PATTERN_DEVIATION": "medium",
    "SPIKE": "medium",
    "COUNT_OVERDUE": "low",
}
LEVEL_RANK: dict[str, int] = {"high": 3, "medium": 2, "low": 1}
RULE_ORDER: tuple[str, ...] = tuple(LEVEL)

MAINTENANCE_GRACE = timedelta(hours=48)
MAINTENANCE_MIN_RATIO = 0.5
PATTERN_MAX_PROBABILITY = 0.01
SPIKE_RATIO = 5
COUNT_MAX_MOVEMENTS = 50
COUNT_MAX_DAYS = 90


@dataclass(frozen=True)
class Hit:
    rule: Rule
    key: str
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def level(self) -> Level:
        return LEVEL[self.rule]


def primary(hits: Sequence[Hit]) -> Hit:
    """한 부품에 여러 규칙이 걸리면 등급이 높은 것, 같으면 규칙 번호가 앞선 것을 대표로 둔다."""
    return min(hits, key=lambda h: (-LEVEL_RANK[h.level], RULE_ORDER.index(h.rule)))


@dataclass(frozen=True)
class LedgerRow:
    id: uuid.UUID
    type: str
    qty: int
    occurred_at: datetime
    maintenance_id: uuid.UUID | None = None


def negative_stock_hit(row: LedgerRow, stock_after: int) -> Hit:
    return Hit(
        "NEGATIVE_STOCK",
        f"NEGATIVE_STOCK:{row.id}",
        {
            "movement_id": str(row.id),
            "occurred_at": row.occurred_at.isoformat(),
            "stock_after": stock_after,
        },
    )


def negative_stock(rows: Sequence[LedgerRow]) -> list[Hit]:
    """F-AUDIT-01. 발생 순 누적이 0 이상에서 0 미만으로 넘어간 원장 행마다 하나.

    rows는 발생 순이어야 한다. 기록 직후 검사(F-LEDGER-03)와 같은 행을 가리켜 한 번만 뜬다.
    """
    hits, total = [], 0
    for row in rows:
        before, total = total, total + row.qty
        if before >= 0 > total:
            hits.append(negative_stock_hit(row, total))
    return hits


def maintenance_mismatch(
    maintenance_id: uuid.UUID,
    completed_at: datetime,
    required_qty: int,
    linked_out_qty: int,
    now: datetime,
) -> Hit | None:
    """F-AUDIT-02. 완료 후 48시간이 지났는데 연결된 출고가 없거나 필요량의 절반 미만."""
    if required_qty <= 0 or now - completed_at < MAINTENANCE_GRACE:
        return None
    if linked_out_qty >= required_qty * MAINTENANCE_MIN_RATIO:
        return None
    return Hit(
        "MAINTENANCE_OUT_MISMATCH",
        f"MAINTENANCE_OUT_MISMATCH:{maintenance_id}",
        {
            "maintenance_id": str(maintenance_id),
            "completed_at": completed_at.isoformat(),
            "required_qty": required_qty,
            "linked_out_qty": linked_out_qty,
        },
    )


def pattern_deviation(weekly_events: Sequence[int]) -> Hit | None:
    """F-AUDIT-03. smooth 부품의 최근 출고 없는 주가 우연일 확률(포아송) 1% 미만.

    weekly_events는 주별 출고 횟수(오래된 주 → 최근 주)다. 최근 연속 0인 주 n을 떼고, 그 전 기간의
    주당 평균 횟수 λ로 P(n주 동안 0회) = exp(-λn)을 계산한다. smooth 판정은 호출하는 쪽이 한다.
    """
    zero_weeks = 0
    for count in reversed(weekly_events):
        if count:
            break
        zero_weeks += 1
    before = weekly_events[: len(weekly_events) - zero_weeks]
    if zero_weeks == 0 or not before:
        return None
    rate = sum(before) / len(before)
    probability = math.exp(-rate * zero_weeks)
    if probability >= PATTERN_MAX_PROBABILITY:
        return None
    return Hit(
        "PATTERN_DEVIATION",
        "PATTERN_DEVIATION",
        {
            "zero_weeks": zero_weeks,
            "weekly_rate": round(rate, 4),
            "probability": round(probability, 6),
        },
    )


def spikes(outs: Sequence[LedgerRow], since: datetime) -> list[Hit]:
    """F-AUDIT-04. since 이후 출고 중 1회 수량이 그 전 출고 최대의 5배를 넘은 것.

    outs는 발생 순 출고(qty 음수)다. 확인 카드에서 확인한 출고도 사후 점검한다.
    """
    hits: list[Hit] = []
    past_max = 0
    for row in outs:
        qty = -row.qty
        if row.occurred_at >= since and past_max and qty > past_max * SPIKE_RATIO:
            hits.append(
                Hit(
                    "SPIKE",
                    f"SPIKE:{row.id}",
                    {
                        "movement_id": str(row.id),
                        "occurred_at": row.occurred_at.isoformat(),
                        "qty": qty,
                        "past_max_qty": past_max,
                    },
                )
            )
        past_max = max(past_max, qty)
    return hits


def count_overdue(
    last_counted_at: datetime | None, since_on: date, movements_since: int, today: date
) -> Hit | None:
    """F-AUDIT-05. 마지막 실사 후 거래 50건 이상 또는 90일 경과.

    since_on은 업무 기준(Asia/Seoul) 마지막 실사일이다. 실사 기록이 없으면 원장 첫 기록일을 넘긴다.
    """
    days = (today - since_on).days
    if movements_since < COUNT_MAX_MOVEMENTS and days < COUNT_MAX_DAYS:
        return None
    return Hit(
        "COUNT_OVERDUE",
        "COUNT_OVERDUE",
        {
            "last_counted_at": last_counted_at.isoformat() if last_counted_at else None,
            "days_since": days,
            "movements_since": movements_since,
        },
    )
