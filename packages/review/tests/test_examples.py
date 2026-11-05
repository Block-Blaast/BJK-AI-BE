"""기능명세서 F-REVIEW-10 예시 5개와 볼트 H_u 변형을 고정한다(비기능 요구사항 정확성)."""

from bjk_review import run_review


def codes(result):
    return [c.code.value for c in result.checks]


def test_vbelt_no_order_needed(case):
    result = run_review(*case("vbelt"))

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


def test_bearing_6205_system_draft_is_ok_but_urgent(case):
    result = run_review(*case("bearing_6205"))

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


def test_bolt_with_confirmed_hidden_stock_needs_no_order(case):
    result = run_review(*case("bolt_confirmed"))

    assert codes(result) == ["C-01", "C-04"]
    assert result.proposal.no_order is True
    assert [c.value for c in result.proposal.basis] == ["C-01", "C-04"]
    assert result.verdict == "revise"
    assert result.flags == []
    assert result.count_requests == []


def test_bolt_with_unconfirmed_hidden_stock_orders_more_and_requests_count(case):
    result = run_review(*case("bolt_unconfirmed"))

    assert codes(result) == ["C-04", "C-07"]
    assert result.checks[0].facts == {"H_c": 0, "H_u": 800}
    assert result.proposal.qty == 80
    assert [c.value for c in result.proposal.basis] == ["C-04", "C-07"]
    assert result.proposal.saving == -3600
    assert result.verdict == "revise"
    assert result.flags == ["caution"]
    assert [r.part_id for r in result.count_requests] == ["p-hexa"]


def test_bearing_6204_switches_supplier_on_price_anomaly(case):
    result = run_review(*case("bearing_6204"))

    assert codes(result) == ["C-05", "C-06"]
    proposal = result.proposal
    assert (proposal.qty, proposal.supplier_name, proposal.unit_price) == (10, "공급사 B", 14800)
    assert proposal.total == 148000
    assert proposal.saving == 62000
    assert [c.value for c in proposal.basis] == ["C-05"]
    assert result.verdict == "revise"
    assert result.flags == []
    assert result.alternatives == []


def test_bearing_6203_keeps_original_and_shows_alternative(case):
    result = run_review(*case("bearing_6203"))

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


def test_same_input_gives_same_result_100_times(case):
    first = run_review(*case("vbelt"))

    assert all(run_review(*case("vbelt")) == first for _ in range(100))
    assert first.review_hash.startswith("sha256:")
