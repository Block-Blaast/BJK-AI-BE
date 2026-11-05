import pytest
from bjk_server.domain.purchase_order import (
    STATUSES,
    OrderStateConflict,
    PriceStats,
    ReceiptOutcome,
    apply_receipt,
    cancel,
    is_open,
    lead_quantiles,
    lead_time_samples,
    mark_ordered,
    price_stats,
)


def test_mark_ordered_and_cancel_only_from_approved():
    assert mark_ordered("approved") == "ordered"
    assert cancel("approved") == "cancelled"
    for status in STATUSES:
        if status == "approved":
            continue
        with pytest.raises(OrderStateConflict) as e:
            mark_ordered(status)
        assert (e.value.status, e.value.action) == (status, "mark_ordered")
        with pytest.raises(OrderStateConflict):
            cancel(status)


def test_partial_then_full_receipt():
    first = apply_receipt("ordered", ordered_qty=10, received_qty=0, qty=4)
    assert first == ReceiptOutcome("partially_received", 4, implicit_order=False, completed=False)
    second = apply_receipt(first.status, 10, first.received_qty, 6)
    assert second == ReceiptOutcome("received", 10, implicit_order=False, completed=True)


def test_over_receipt_completes():
    assert apply_receipt("ordered", 10, 0, 12).status == "received"


def test_receipt_without_mark_ordered_is_implicit_order():
    outcome = apply_receipt("approved", 10, 0, 10)
    assert outcome.status == "received"
    assert outcome.implicit_order is True
    assert apply_receipt("approved", 10, 0, 3).status == "partially_received"


@pytest.mark.parametrize("status", ["received", "cancelled"])
def test_no_receipt_on_final_status(status):
    with pytest.raises(OrderStateConflict):
        apply_receipt(status, 10, 10, 1)


@pytest.mark.parametrize(("ordered", "received", "qty"), [(0, 0, 1), (10, -1, 1), (10, 0, 0)])
def test_rejects_invalid_quantities(ordered, received, qty):
    with pytest.raises(ValueError):
        apply_receipt("ordered", ordered, received, qty)


def test_open_statuses():
    assert [s for s in STATUSES if is_open(s)] == ["approved", "ordered", "partially_received"]


def test_same_input_same_output():
    assert apply_receipt("ordered", 7, 2, 3) == apply_receipt("ordered", 7, 2, 3)


def test_price_stats():
    assert price_stats([]) == PriceStats(mean=None, std=None, n=0)
    assert price_stats([15000]) == PriceStats(mean=15000.0, std=0.0, n=1)
    stats = price_stats([15000, 16000, 14000])
    assert (stats.mean, stats.std, stats.n) == (15000.0, 1000.0, 3)


def test_lead_time_samples_fall_back_to_supplier():
    assert lead_time_samples([5, 6, 7], [1, 2]) == [5, 6, 7]
    assert lead_time_samples([5, 6], [5, 6, 9, 9]) == [5, 6, 9, 9]
    assert lead_time_samples([], []) == []


def test_lead_quantiles():
    assert lead_quantiles([5, 6, 7, 8], False, 2.0, 0.25) == (7, 8)  # 6.5 → 7, 7.7 → 8
    # 수입 의존: 표본마다 1 + 0.25 × 2 = 1.5배
    assert lead_quantiles([4, 4, 4], True, 2.0, 0.25) == (6, 6)
    with pytest.raises(ValueError):
        lead_quantiles([], False, 0, 0.25)
