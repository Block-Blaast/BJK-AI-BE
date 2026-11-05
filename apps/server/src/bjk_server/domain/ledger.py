"""원장 실시간 체크 규칙 (기능명세서 F-LEDGER-03). 순수 함수."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta

SCHEDULE_WINDOW_DAYS = 1
AFTER_COMPLETION = timedelta(hours=48)


@dataclass(frozen=True)
class MaintenanceSlot:
    id: uuid.UUID
    scheduled_date: date
    completed_at: datetime | None


def pick_maintenance(
    occurred_at: datetime, occurred_on: date, slots: Sequence[MaintenanceSlot]
) -> uuid.UUID | None:
    """출고를 연결할 정비. 예정일 ±1일 안이거나 완료 후 48시간 안인 정비 중 가장 가까운 것.

    occurred_on은 업무 기준(Asia/Seoul) 날짜다. 같은 거리면 예정일이 이른 정비를 고른다.
    """
    best: tuple[float, date, uuid.UUID] | None = None
    for slot in slots:
        distances = []
        day_gap = abs((occurred_on - slot.scheduled_date).days)
        if day_gap <= SCHEDULE_WINDOW_DAYS:
            distances.append(float(day_gap))
        if slot.completed_at is not None:
            since = occurred_at - slot.completed_at
            if timedelta(0) <= since <= AFTER_COMPLETION:
                distances.append(since / timedelta(days=1))
        if distances:
            key = (min(distances), slot.scheduled_date, slot.id)
            best = key if best is None or key < best else best
    return best[2] if best else None
