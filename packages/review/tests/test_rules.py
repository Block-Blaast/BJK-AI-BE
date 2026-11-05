from datetime import date, datetime

import pytest
from bjk_review import (
    OpenRequest,
    OrderRequest,
    PriceStats,
    PriceTier,
    ReviewSettings,
    ReviewSnapshot,
    SupplierOffer,
    run_review,
)

AS_OF = date(2026, 11, 4)

SUP_A = SupplierOffer(supplier_id="sup-a", name="공급사 A", unit_price=10000, lt90=5)


def snapshot(**values):
    defaults = {
        "as_of": AS_OF,
        "computed_at": datetime.fromisoformat("2026-11-04T03:00:00+09:00"),
        "part_id": "p-1",
        "stock": 5,
        "m": 4,
        "d95": 15,
        "d99": 18,
        "default_supplier_id": "sup-a",
        "suppliers": [SUP_A],
    }
    return ReviewSnapshot(**{**defaults, **values})


def codes(result):
    return [c.code.value for c in result.checks]


@pytest.mark.parametrize(
    ("values", "request_supplier", "reasons"),
    [
        ({"part_id": None}, "sup-a", ["part_unresolved"]),
        ({"default_supplier_id": None}, None, ["supplier_unresolved"]),
        ({"default_supplier_id": "sup-a"}, "sup-x", ["supplier_unresolved"]),
        ({"has_usage_history": False}, "sup-a", ["no_demand_data"]),
    ],
)
def test_hold_skips_checks(values, request_supplier, reasons):
    result = run_review(snapshot(**values), OrderRequest(qty=10, supplier_id=request_supplier))

    assert result.verdict == "hold"
    assert [r.value for r in result.hold_reasons] == reasons
    assert result.checks == []
    assert result.proposal is None


def test_usage_estimate_alone_avoids_hold():
    snap = snapshot(has_usage_history=False, has_usage_estimate=True)
    assert run_review(snap, OrderRequest(qty=10)).verdict != "hold"


def test_ok_when_request_matches_recommendation():
    result = run_review(snapshot(), OrderRequest(qty=10, supplier_id="sup-a", unit_price=10000))

    assert result.checks == []
    assert result.verdict == "ok"
    assert result.flags == []
    assert result.proposal.basis == []


def test_short_quantity_raises_to_recommended_and_reports_extra_cost():
    result = run_review(snapshot(loss=500000), OrderRequest(qty=4, unit_price=10000))

    assert codes(result) == ["C-07"]
    assert result.proposal.qty == 10
    assert result.proposal.saving == -60000
    assert result.verdict == "revise"
    assert "urgent" not in result.flags


def test_other_open_request_counts_as_duplicate_and_reduces_recommendation():
    snap = snapshot(open_requests=[OpenRequest(review_id="rv-9", qty=6)])
    result = run_review(snap, OrderRequest(qty=10, unit_price=10000))

    assert codes(result) == ["C-03"]
    assert result.checks[0].facts == {"open_request_qty": 6}
    assert result.proposal.qty == 4


def test_no_recent_usage_flags_long_term_stock():
    snap = snapshot(m=0, has_maintenance_plan=True, d95=0, d99=0)
    result = run_review(snap, OrderRequest(qty=3, unit_price=10000))

    c02 = next(c for c in result.checks if c.code == "C-02")
    assert c02.facts["note"] == "no_recent_usage"


def test_supplier_lead_too_long_switches_to_in_time_supplier():
    slow = SupplierOffer(supplier_id="sup-a", name="공급사 A", unit_price=9000, lt90=20)
    fast = SupplierOffer(supplier_id="sup-b", name="공급사 B", unit_price=11000, lt90=5)
    snap = snapshot(suppliers=[slow, fast], t_out=date(2026, 11, 14))
    result = run_review(snap, OrderRequest(qty=10, supplier_id="sup-a", unit_price=9000))

    assert codes(result) == ["C-08"]
    assert result.checks[0].facts["cause"] == "supplier_lead"
    assert result.proposal.supplier_id == "sup-b"
    assert [c.value for c in result.proposal.basis] == ["C-08"]
    assert result.flags == ["urgent"]


def test_no_supplier_in_time_picks_fastest_and_stays_urgent():
    slow = SupplierOffer(supplier_id="sup-a", name="공급사 A", unit_price=9000, lt90=20)
    slower = SupplierOffer(supplier_id="sup-b", name="공급사 B", unit_price=8000, lt90=15)
    snap = snapshot(suppliers=[slow, slower], t_out=date(2026, 11, 10))
    result = run_review(snap, OrderRequest(qty=10, supplier_id="sup-a", unit_price=9000))

    assert result.proposal.supplier_id == "sup-b"
    assert "urgent" in result.flags


def test_price_anomaly_without_cheaper_supplier_keeps_original_with_caution():
    snap = snapshot(price_stats=PriceStats(mean=8000, sigma=200, n=5))
    result = run_review(snap, OrderRequest(qty=10, supplier_id="sup-a", unit_price=10000))

    assert codes(result) == ["C-05"]
    assert result.verdict == "ok"
    assert result.flags == ["caution"]


def test_price_anomaly_with_small_saving_keeps_supplier():
    near = SupplierOffer(supplier_id="sup-b", name="공급사 B", unit_price=9500, lt90=5)
    snap = snapshot(suppliers=[SUP_A, near], price_stats=PriceStats(mean=8000, sigma=200, n=5))
    result = run_review(snap, OrderRequest(qty=10, supplier_id="sup-a", unit_price=10000))

    assert result.proposal.supplier_id == "sup-a"
    assert result.flags == ["caution"]


@pytest.mark.parametrize(
    ("n", "price", "hit"), [(2, 11600, True), (2, 11400, False), (0, 99999, False)]
)
def test_price_anomaly_small_sample_threshold(n, price, hit):
    snap = snapshot(price_stats=PriceStats(mean=10000 if n else None, n=n))
    result = run_review(snap, OrderRequest(qty=10, supplier_id="sup-a", unit_price=price))

    assert ("C-05" in codes(result)) is hit


def test_price_tier_alternative_within_five_percent():
    offer = SupplierOffer(
        supplier_id="sup-a",
        name="공급사 A",
        unit_price=10000,
        lt90=5,
        price_tiers=[PriceTier(min_qty=12, unit_price=8700)],
    )
    result = run_review(snapshot(suppliers=[offer]), OrderRequest(qty=10, unit_price=10000))

    assert result.verdict == "ok"
    [alternative] = result.alternatives
    assert (alternative.kind, alternative.qty, alternative.total) == ("price_tier", 12, 104400)
    assert result.flags == ["alternative"]


def test_price_tier_alternative_not_beyond_d99():
    offer = SupplierOffer(
        supplier_id="sup-a",
        name="공급사 A",
        unit_price=10000,
        lt90=5,
        price_tiers=[PriceTier(min_qty=20, unit_price=5000)],
    )
    result = run_review(snapshot(suppliers=[offer]), OrderRequest(qty=10, unit_price=10000))

    assert result.alternatives == []


def test_external_risk_is_info_and_does_not_change_verdict():
    snap = snapshot(import_dependent=True, r_price=2.2, holidays_in_lead=["춘절"])
    result = run_review(snap, OrderRequest(qty=10, unit_price=10000))

    assert codes(result) == ["C-09"]
    assert result.checks[0].facts == {"r_lead": 0, "r_price": 2.2, "holiday": "춘절"}
    assert result.verdict == "ok"
    assert result.flags == []


def test_settings_change_threshold_and_hash():
    snap = snapshot(t_deadline=date(2026, 11, 11))
    request = OrderRequest(qty=10, unit_price=10000)
    default = run_review(snap, request)
    wider = run_review(snap, request, ReviewSettings(c08_days=7))

    assert "C-08" not in codes(default)
    assert "C-08" in codes(wider)
    assert default.review_hash != wider.review_hash
