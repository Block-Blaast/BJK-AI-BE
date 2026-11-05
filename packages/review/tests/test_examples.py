"""기능명세서 F-REVIEW-10 예시 5개와 볼트 H_u 변형을 고정한다(비기능 요구사항 정확성).

예시 표에 없는 값(공급사 납기·MOQ·배송비, D99 등)은 예시의 판정이 성립하는 범위에서 정했다.
"""

from datetime import date, datetime

from bjk_review import (
    HiddenStock,
    OpenOrder,
    OrderRequest,
    PriceStats,
    PriceTier,
    ReviewSnapshot,
    SupplierOffer,
    run_review,
)

AS_OF = date(2026, 11, 4)
COMPUTED_AT = datetime.fromisoformat("2026-11-04T03:00:00+09:00")


def snapshot(**values):
    defaults = {"as_of": AS_OF, "computed_at": COMPUTED_AT, "part_id": "p-1"}
    return ReviewSnapshot(**{**defaults, **values})


def codes(result):
    return [c.code.value for c in result.checks]


def vbelt():
    return snapshot(
        part_name="V벨트 A-42",
        stock=2,
        incoming=10,
        open_orders=[OpenOrder(qty=10, eta=date(2026, 11, 8))],
        m=1.5,
        d95=4,
        d99=5,
        default_supplier_id="sup-a",
        suppliers=[
            SupplierOffer(supplier_id="sup-a", name="공급사 A", unit_price=18000, lt90=7),
            SupplierOffer(supplier_id="sup-b", name="공급사 B", unit_price=15000, moq=5, lt90=8),
        ],
        price_stats=PriceStats(mean=13000, sigma=1200, n=4),
    )


def test_vbelt_no_order_needed():
    result = run_review(vbelt(), OrderRequest(qty=30, supplier_id="sup-a", unit_price=18000))

    assert codes(result) == ["C-01", "C-02", "C-03", "C-05", "C-06"]
    facts = {c.code.value: c.facts for c in result.checks}
    assert facts["C-01"] == {"S": 2, "O": 10, "H_c": 0, "Q": 30, "D99": 5, "MOQ": 1}
    assert facts["C-02"]["months"] == 20
    assert facts["C-03"] == {"incoming_qty": 10, "eta": "2026-11-08"}
    assert facts["C-05"] == {"unit_price": 18000, "p_mean": 13000, "sigma": 1200, "n": 4}
    assert facts["C-06"] == {"supplier": "공급사 B", "unit_price": 15000, "LT90": 8}
    assert result.original.total == 540000
    assert result.proposal.no_order is True
    assert (result.proposal.qty, result.proposal.total) == (0, 0)
    assert result.proposal.saving == 540000
    assert [c.value for c in result.proposal.basis] == ["C-01", "C-02", "C-03"]
    assert result.verdict == "revise"
    assert result.flags == []
    assert result.alternatives == []


def test_bearing_6205_system_draft_is_ok_but_urgent():
    snap = snapshot(
        part_name="볼베어링 6205ZZ",
        stock=3,
        f_period=4,
        f_12m=16,
        m=0.5,
        d95=11,
        d99=13,
        t_out=date(2026, 11, 20),
        t_deadline=date(2026, 11, 9),
        default_supplier_id="sup-a",
        suppliers=[
            SupplierOffer(
                supplier_id="sup-a",
                name="공급사 A",
                unit_price=18000,
                moq=10,
                price_tiers=[PriceTier(min_qty=20, unit_price=16500)],
                shipping_fee=4000,
                lt90=11,
            )
        ],
        import_dependent=True,
        r_lead=1.5,
    )
    result = run_review(snap, OrderRequest(qty=10))

    assert codes(result) == ["C-08", "C-09"]
    c08 = result.checks[0]
    assert c08.level == "urgent"
    assert c08.facts["days_left"] == 5
    assert c08.facts["cause"] == "deadline"
    assert result.original.total == 180000
    assert result.proposal.qty == 10
    assert result.proposal.basis == []
    assert result.verdict == "ok"
    assert result.flags == ["urgent"]


def bolt(confirmed):
    return snapshot(
        part_name="볼트 M8×20",
        stock=40,
        hidden=[HiddenStock(part_id="p-hexa", name="헥사볼트 M8x20", qty=800, confirmed=confirmed)],
        m=30,
        d95=120,
        d99=130,
        default_supplier_id="sup-a",
        suppliers=[
            SupplierOffer(supplier_id="sup-a", name="공급사 A", unit_price=120, moq=10, lt90=3)
        ],
    )


def test_bolt_with_confirmed_hidden_stock_needs_no_order():
    result = run_review(bolt(confirmed=True), OrderRequest(qty=50, supplier_id="sup-a"))

    assert codes(result) == ["C-01", "C-04"]
    assert result.proposal.no_order is True
    assert [c.value for c in result.proposal.basis] == ["C-01", "C-04"]
    assert result.verdict == "revise"
    assert result.flags == []
    assert result.count_requests == []


def test_bolt_with_unconfirmed_hidden_stock_orders_more_and_requests_count():
    result = run_review(bolt(confirmed=False), OrderRequest(qty=50, supplier_id="sup-a"))

    assert codes(result) == ["C-04", "C-07"]
    assert result.checks[0].facts == {"H_c": 0, "H_u": 800}
    assert result.proposal.qty == 80
    assert [c.value for c in result.proposal.basis] == ["C-04", "C-07"]
    assert result.proposal.saving == -3600
    assert result.verdict == "revise"
    assert result.flags == ["caution"]
    assert [r.part_id for r in result.count_requests] == ["p-hexa"]


def test_bearing_6204_switches_supplier_on_price_anomaly():
    snap = snapshot(
        part_name="볼베어링 6204ZZ",
        stock=2,
        m=4,
        d95=12,
        d99=14,
        t_out=date(2026, 11, 30),
        default_supplier_id="sup-a",
        suppliers=[
            SupplierOffer(
                supplier_id="sup-a", name="공급사 A", unit_price=21000, shipping_fee=4000, lt90=5
            ),
            SupplierOffer(
                supplier_id="sup-b",
                name="공급사 B",
                unit_price=14800,
                moq=10,
                shipping_fee=3000,
                lt90=6,
            ),
        ],
        price_stats=PriceStats(mean=15500, sigma=900, n=5),
    )
    result = run_review(snap, OrderRequest(qty=10, supplier_id="sup-a", unit_price=21000))

    assert codes(result) == ["C-05", "C-06"]
    proposal = result.proposal
    assert (proposal.qty, proposal.supplier_name, proposal.unit_price) == (10, "공급사 B", 14800)
    assert proposal.total == 148000
    assert proposal.saving == 62000
    assert [c.value for c in proposal.basis] == ["C-05"]
    assert result.verdict == "revise"
    assert result.flags == []
    assert result.alternatives == []


def test_bearing_6203_keeps_original_and_shows_alternative():
    snap = snapshot(
        part_name="볼베어링 6203ZZ",
        stock=2,
        m=4,
        d95=12,
        d99=14,
        t_out=date(2026, 11, 30),
        default_supplier_id="sup-a",
        suppliers=[
            SupplierOffer(supplier_id="sup-a", name="공급사 A", unit_price=9000, lt90=5),
            SupplierOffer(supplier_id="sup-c", name="공급사 C", unit_price=7900, lt90=6),
        ],
        price_stats=PriceStats(mean=9000, sigma=300, n=5),
    )
    result = run_review(snap, OrderRequest(qty=10, supplier_id="sup-a", unit_price=9000))

    assert codes(result) == ["C-06"]
    assert result.proposal.basis == []
    assert result.verdict == "ok"
    assert result.flags == ["alternative"]
    [alternative] = result.alternatives
    assert alternative.kind == "cheaper_supplier"
    assert (alternative.supplier_name, alternative.qty, alternative.total) == (
        "공급사 C",
        10,
        79000,
    )
    assert alternative.saving == 11000


def test_same_input_gives_same_result_100_times():
    request = OrderRequest(qty=30, supplier_id="sup-a", unit_price=18000)
    first = run_review(vbelt(), request)

    assert all(run_review(vbelt(), request) == first for _ in range(100))
    assert first.review_hash.startswith("sha256:")
