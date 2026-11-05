"""발주 상태 전이 규칙 (API 명세서 PO-03·04, 기능명세서 F-LEDGER-04). 순수 함수.

상태: approved(주문 대기) → ordered(발주됨) → partially_received(부분입고) → received(입고완료).
cancelled(취소)는 approved에서만 갈 수 있다. received·cancelled는 끝 상태다.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal

PoStatus = Literal["approved", "ordered", "partially_received", "received", "cancelled"]
PoAction = Literal["mark_ordered", "cancel", "receive"]

STATUSES: tuple[PoStatus, ...] = (
    "approved",
    "ordered",
    "partially_received",
    "received",
    "cancelled",
)
# 입고 예정(열린 발주)으로 계산하는 상태
OPEN_STATUSES: frozenset[PoStatus] = frozenset({"approved", "ordered", "partially_received"})
FINAL_STATUSES: frozenset[PoStatus] = frozenset({"received", "cancelled"})

# 행동별로 받을 수 있는 현재 상태
ALLOWED_FROM: dict[PoAction, frozenset[PoStatus]] = {
    "mark_ordered": frozenset({"approved"}),
    "cancel": frozenset({"approved"}),
    "receive": OPEN_STATUSES,
}


class OrderStateConflict(Exception):
    """현재 상태에서 할 수 없는 행동. API에서는 409 ORDER_STATE_CONFLICT로 바꾼다."""

    def __init__(self, status: PoStatus, action: PoAction) -> None:
        super().__init__(f"{action} not allowed from {status}")
        self.status = status
        self.action = action


def _check(status: PoStatus, action: PoAction) -> None:
    if status not in ALLOWED_FROM[action]:
        raise OrderStateConflict(status, action)


def mark_ordered(status: PoStatus) -> PoStatus:
    """주문 완료 표시. 승인됨에서만."""
    _check(status, "mark_ordered")
    return "ordered"


def cancel(status: PoStatus) -> PoStatus:
    """주문하지 않기로 함. 승인됨에서만."""
    _check(status, "cancel")
    return "cancelled"


@dataclass(frozen=True)
class ReceiptOutcome:
    status: PoStatus
    received_qty: int
    # 주문 완료 표시 없이 입고돼 서버가 ordered로 바꾼 건. 실제 납기 표본에서 뺀다.
    implicit_order: bool
    # 이번 입고로 발주 수량을 모두 채움. 실제 납기는 이 입고 시각으로 잰다.
    completed: bool


def apply_receipt(
    status: PoStatus, ordered_qty: int, received_qty: int, qty: int
) -> ReceiptOutcome:
    """입고 qty개를 발주에 반영한 결과.

    received_qty는 이전까지 누적 입고 수량이다. 누적이 발주 수량 이상이면 입고완료,
    그보다 적으면 부분입고. 발주 수량을 넘는 입고도 입고완료로 본다.
    """
    if ordered_qty <= 0 or received_qty < 0 or qty <= 0:
        raise ValueError("수량은 발주 수량·입고 수량 양수, 누적 입고 0 이상이어야 합니다.")
    _check(status, "receive")
    total = received_qty + qty
    completed = total >= ordered_qty
    return ReceiptOutcome(
        status="received" if completed else "partially_received",
        received_qty=total,
        implicit_order=status == "approved",
        completed=completed,
    )


def is_open(status: PoStatus) -> bool:
    return status in OPEN_STATUSES


@dataclass(frozen=True)
class PriceStats:
    """최근 구매 단가의 평균 p̄, 표준편차 σ_p, 건수 n (F-REVIEW-02, C-05).

    건수가 0이면 평균·표준편차는 None.
    """

    mean: float | None
    std: float | None
    n: int


def price_stats(prices: Sequence[int]) -> PriceStats:
    """표본 표준편차(n − 1). 한 건이면 표준편차 0."""
    n = len(prices)
    if n == 0:
        return PriceStats(mean=None, std=None, n=0)
    mean = sum(prices) / n
    if n == 1:
        return PriceStats(mean=mean, std=0.0, n=1)
    variance = sum((p - mean) ** 2 for p in prices) / (n - 1)
    return PriceStats(mean=mean, std=math.sqrt(variance), n=n)


def order_message(part_name: str, qty: int, unit: str, need_by: date | None) -> str:
    """공급사에 보낼 문자 문구 (F-APPROVAL-03). 희망 납기는 필요 시점(t_need)이 있을 때만."""
    text = f"안녕하세요. {part_name} {qty}{unit} 주문 부탁드립니다."
    if need_by is not None:
        text += f" {need_by.month}월 {need_by.day}일까지 받을 수 있을까요?"
    return text
