"""회사 설정 기본값 (API 명세서 SYS-01)."""

import copy
from typing import Any

DEFAULT_SETTINGS: dict[str, dict[str, Any]] = {
    "notify": {
        "quiet_hours": {"start": "21:00", "end": "07:00"},
        "briefing_time": "07:30",
    },
    "review": {
        "service_level": {"A": 0.98, "B": 0.95, "C": 0.90},
        "next_order_weeks": 4,
        "c02_months": 12,
        "c05_sigma": 2,
        "c06_ratio": 0.9,
        "c08_days": 5,
    },
    "system": {
        "c05_min_ratio": 1.05,
        "c05_small_n_ratio": 1.15,
        "hidden_stock_count_days": 30,
        "review_expire_days": 7,
        "missed_p_out_min": 0.3,
        "match_confirm_cosine": 0.85,
        "match_confirm_gap": 0.05,
        "external_k": 0.25,
        "count_per_worker_per_day": 2,
        "count_suppress_days": 30,
    },
}


def default_settings() -> dict[str, dict[str, Any]]:
    return copy.deepcopy(DEFAULT_SETTINGS)
