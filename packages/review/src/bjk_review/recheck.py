"""재검토 (F-REVIEW-09).

- 직접 수정: 승인자가 바꾼 수량·공급사·단가로 같은 스냅샷을 다시 판정한다(REV-04, 저장 안 함).
- 승인 직전 갱신: 검토 후 같은 부품 입출고가 있었거나 계산이 24시간을 넘었으면 server가 새
  스냅샷으로 다시 판정하고, 판정·수정안이 바뀌었으면 다시 확인받는다(REV-05 `SNAPSHOT_REFRESHED`).
"""

from datetime import datetime, timedelta

from bjk_review.engine import run_review
from bjk_review.models import OrderRequest, ReviewResult, ReviewSettings, ReviewSnapshot

SNAPSHOT_MAX_AGE = timedelta(hours=24)


def recheck(
    snapshot: ReviewSnapshot, edited: OrderRequest, settings: ReviewSettings | None = None
) -> ReviewResult:
    """직접 수정 값으로 다시 판정. 결과의 `review_hash`가 REV-04의 `recheck_hash`다.

    승인(`approve_edited`) 때 같은 스냅샷·수정 값으로 다시 계산한 해시와 대조하면, 미리 본
    결과와 승인한 결과가 같다는 것을 확인할 수 있다.
    """
    return run_review(snapshot, edited, settings)


def needs_refresh(snapshot: ReviewSnapshot, *, now: datetime, part_moved_since: bool) -> bool:
    """승인 직전 스냅샷을 새로 모아야 하는지. `now`는 호출하는 쪽이 넘긴다(순수 함수)."""
    return part_moved_since or now - snapshot.computed_at > SNAPSHOT_MAX_AGE


def decision_changed(before: ReviewResult, after: ReviewResult) -> bool:
    """판정 또는 수정안(수량·공급사·단가)이 바뀌었는지."""
    if before.verdict != after.verdict:
        return True

    def key(result: ReviewResult):
        p = result.proposal
        return None if p is None else (p.qty, p.supplier_id, p.unit_price)

    return key(before) != key(after)
