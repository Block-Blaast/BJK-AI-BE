import math
from datetime import date

import numpy as np
import pytest
from bjk_server.domain import analytics as an
from bjk_server.domain.external import indicator_risk, risk_level


@pytest.mark.parametrize(
    ("weekly", "expected"),
    [
        ([5, 5, 6, 5, 5, 6, 5, 5], "smooth"),  # ADI 1, CV² 작음
        ([1, 9, 1, 9, 1, 9, 1, 9], "erratic"),  # ADI 1, CV² 큼
        ([0, 3, 0, 0, 3, 0, 0, 3, 0, 3], "intermittent"),  # ADI 2.5, 크기 일정
        ([0, 1, 0, 0, 9, 0, 0, 1, 0, 9], "lumpy"),  # ADI 2.5, 크기 들쭉날쭉
        ([1, 1, 1, 1, 1, 1, 1], "insufficient"),  # 8주 미만
    ],
)
def test_classify_by_adi_and_cv2(weekly, expected):
    assert an.classify(weekly) == expected


def test_ses_forecast():
    # level: 10 → 0.1*20 + 0.9*10 = 11
    assert an.forecast_weekly([10, 20], "smooth") == pytest.approx(11)


def test_sba_forecast():
    # 수요 3이 2주 간격으로 반복: z = 3, p = 2 → (1 - 0.05) * 3 / 2
    assert an.forecast_weekly([0, 3, 0, 3, 0, 3], "intermittent") == pytest.approx(0.95 * 1.5)
    assert an.forecast_weekly([0, 0, 0], "lumpy") == 0


def test_abc_by_cumulative_share():
    usage = {"a": 70, "b": 15, "c": 10, "d": 5}
    assert an.abc_classes(usage) == {"a": "A", "b": "A", "c": "B", "d": "C"}
    assert an.abc_classes({"x": 0, "y": 0}) == {"x": "C", "y": "C"}


def test_bootstrap_is_reproducible_with_seed():
    weekly = [0, 2, 1, 0, 3]
    seed = an.seed_for("c", "p", date(2026, 11, 4))
    first = an.bootstrap_demand(weekly, 14, np.random.default_rng(seed))
    again = an.bootstrap_demand(weekly, 14, np.random.default_rng(seed))
    assert np.array_equal(first, again)
    assert seed != an.seed_for("c", "p", date(2026, 11, 5))


def test_upper_quantile_adds_fixed_demand():
    samples = np.arange(100, dtype=float)
    assert an.upper_quantile(samples, 0.95, fixed=4) == math.ceil(np.quantile(samples, 0.95) + 4)


def test_poisson_without_estimate_is_zero():
    assert not an.poisson_demand(None, 30, np.random.default_rng(1)).any()


def test_path_simulation_hits_on_maintenance_day():
    # 통계 수요 0, 재고 3, 16일 뒤 정비로 4개 → 16일째 소진, 10일 안 결품 확률 0
    result = an.simulate_paths(
        3, np.zeros(5), [(16, 4)], arrival_day=10, rng=np.random.default_rng(1)
    )
    assert result == an.PathResult(t_out_day=16, p_out=0.0)


def test_path_simulation_without_stockout():
    result = an.simulate_paths(100, np.zeros(5), [], arrival_day=10, rng=np.random.default_rng(1))
    assert result.t_out_day is None


def test_recommended_qty_rounds_up_to_moq():
    # 기능명세서 F-REVIEW-10: R = 8 → MOQ 10
    assert an.recommended_qty(d95=11, stock=3, incoming=0, hidden_confirmed=0, moq=10) == 10
    assert an.recommended_qty(d95=4, stock=2, incoming=10, hidden_confirmed=0, moq=1) == 0


def test_expected_loss_formula():
    # 시간당 손실 50,000원 × 가동 16시간 × LT50 6일 (API 명세서 SET-04 예시)
    assert an.expected_loss([(50_000, 16)], 6) == 4_800_000


def test_indicator_risk_only_counts_unfavorable_direction():
    rising = [100 * 1.01**i for i in range(30)] + [200]
    falling = [100 * 1.01**i for i in range(30)] + [50]
    z_up, r_up = indicator_risk(rising)
    z_down, r_down = indicator_risk(falling)
    assert z_up > 0 and r_up == 4.0  # 상한 4
    assert z_down < 0 and r_down == 0.0
    assert indicator_risk([1, 2, 3]) == (None, 0.0)


@pytest.mark.parametrize(("r", "level"), [(0.99, "normal"), (1.0, "caution"), (2.0, "high")])
def test_risk_levels(r, level):
    assert risk_level(r) == level
