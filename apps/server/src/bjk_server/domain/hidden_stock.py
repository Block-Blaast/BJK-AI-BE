"""숨은 재고 (기능명세서 F-MATCH-03). 순수 함수.

같은 규격으로 등록된 다른 부품(병합 전)의 재고를 확인된 숨은 재고 H_c와 미확인 숨은 재고 H_u로
나눈다. 권장 발주량과 수량 체크는 H_c만 빼고, H_u는 실사 요청으로 돌린다(설계 원칙 9).
"""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any


@dataclass(frozen=True)
class HiddenPart:
    part_id: uuid.UUID
    qty: int
    # 마지막 실사 응답 시각. 실사 기록이 없으면 None
    last_counted_at: datetime | None
    # 열린 장부 의심 항목이 있음 (장부 상태 suspect)
    suspect: bool


@dataclass(frozen=True)
class HiddenStock:
    confirmed: tuple[HiddenPart, ...] = ()
    unconfirmed: tuple[HiddenPart, ...] = ()

    @property
    def h_c(self) -> int:
        return sum(p.qty for p in self.confirmed)

    @property
    def h_u(self) -> int:
        return sum(p.qty for p in self.unconfirmed)


def same_spec(
    category_id: uuid.UUID | None,
    spec: dict[str, Any] | None,
    other_category_id: uuid.UUID | None,
    other_spec: dict[str, Any] | None,
) -> bool:
    """같은 카테고리에 같은 규격으로 등록됐는가. 규격이 없는 부품은 숨은 재고를 따지지 않는다."""
    return bool(spec) and category_id == other_category_id and spec == other_spec


def is_confirmed(part: HiddenPart, now: datetime, count_days: int) -> bool:
    """마지막 실사가 count_days 이내이고 장부 상태가 의심이 아니면 확인된 재고다."""
    if part.suspect or part.last_counted_at is None:
        return False
    return now - part.last_counted_at <= timedelta(days=count_days)


def split_hidden(parts: Iterable[HiddenPart], now: datetime, count_days: int) -> HiddenStock:
    """같은 규격 부품들을 H_c·H_u로 나눈다. 재고가 0 이하인 부품은 숨은 재고가 아니다."""
    confirmed: list[HiddenPart] = []
    unconfirmed: list[HiddenPart] = []
    for part in parts:
        if part.qty <= 0:
            continue
        (confirmed if is_confirmed(part, now, count_days) else unconfirmed).append(part)
    return HiddenStock(tuple(confirmed), tuple(unconfirmed))
