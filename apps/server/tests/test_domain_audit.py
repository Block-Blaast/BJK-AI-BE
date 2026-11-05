import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from bjk_server.domain import audit as rules
from bjk_server.domain.audit import Hit, LedgerRow

T0 = datetime(2026, 11, 1, 1, 0, tzinfo=UTC)


def _rows(*qtys: int) -> list[LedgerRow]:
    return [
        LedgerRow(uuid.uuid4(), "IN" if q > 0 else "OUT", q, T0 + timedelta(hours=i))
        for i, q in enumerate(qtys)
    ]


def test_negative_stock_hits_each_crossing_below_zero():
    rows = _rows(3, -5, -1, 10, -20)
    hits = rules.negative_stock(rows)
    assert [h.evidence["stock_after"] for h in hits] == [-2, -13]
    assert [h.key for h in hits] == [f"NEGATIVE_STOCK:{rows[1].id}", f"NEGATIVE_STOCK:{rows[4].id}"]
    assert all(h.level == "high" for h in hits)


def test_negative_stock_ignores_ledger_that_stays_non_negative():
    assert rules.negative_stock(_rows(3, -3, 5, -1)) == []


@pytest.mark.parametrize(
    ("hours_after", "required", "linked", "hit"),
    [
        (47, 100, 0, False),  # 48시간 전
        (49, 100, 0, True),
        (49, 100, 49, True),  # 절반 미만
        (49, 100, 50, False),
        (49, 0, 0, False),
    ],
)
def test_maintenance_mismatch(hours_after, required, linked, hit):
    mid = uuid.uuid4()
    result = rules.maintenance_mismatch(
        mid, T0, required, linked, T0 + timedelta(hours=hours_after)
    )
    assert (result is not None) == hit
    if hit:
        assert result.key == f"MAINTENANCE_OUT_MISMATCH:{mid}"
        assert result.evidence["required_qty"] == required
        assert result.evidence["linked_out_qty"] == linked


def test_pattern_deviation_uses_poisson_probability_of_recent_zero_weeks():
    # 주 2회 나가던 부품이 3주 동안 0회: exp(-6) ≈ 0.0025 < 1%
    hit = rules.pattern_deviation([2, 2, 2, 2, 0, 0, 0])
    assert hit is not None and hit.level == "medium"
    assert hit.evidence["zero_weeks"] == 3
    assert hit.evidence["probability"] == pytest.approx(0.002479, abs=1e-6)
    # 주 1회 부품의 1주 공백: exp(-1) ≈ 0.37
    assert rules.pattern_deviation([1, 1, 1, 0]) is None
    assert rules.pattern_deviation([1, 1, 1]) is None
    assert rules.pattern_deviation([0, 0]) is None


def test_spikes_compare_with_previous_max_after_since():
    rows = _rows(-2, -3, -20, -16, -100)
    hits = rules.spikes(rows, since=rows[2].occurred_at)
    # -20 > 3 × 5, -16 < 20 × 5, -100 = 20 × 5 (초과만)
    assert [h.evidence["qty"] for h in hits] == [20]
    assert hits[0].evidence["past_max_qty"] == 3
    assert hits[0].key == f"SPIKE:{rows[2].id}"
    assert rules.spikes(rows, since=rows[-1].occurred_at + timedelta(hours=1)) == []


@pytest.mark.parametrize(
    ("days", "movements", "hit"),
    [(89, 49, False), (90, 0, True), (10, 50, True)],
)
def test_count_overdue(days, movements, hit):
    today = date(2026, 11, 4)
    result = rules.count_overdue(None, today - timedelta(days=days), movements, today)
    assert (result is not None) == hit
    if hit:
        assert result.level == "low"
        assert result.evidence == {
            "last_counted_at": None,
            "days_since": days,
            "movements_since": movements,
        }


def test_primary_prefers_level_then_rule_order():
    low = Hit("COUNT_OVERDUE", "COUNT_OVERDUE")
    spike = Hit("SPIKE", "SPIKE:x")
    pattern = Hit("PATTERN_DEVIATION", "PATTERN_DEVIATION")
    mismatch = Hit("MAINTENANCE_OUT_MISMATCH", "MAINTENANCE_OUT_MISMATCH:y")
    assert rules.primary([low, spike, pattern]) is pattern
    assert rules.primary([low, spike, mismatch]) is mismatch
