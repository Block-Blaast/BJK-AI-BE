"""회사 생성 시 넣는 기본값. 설정(API 명세서 SYS-01)과 기본 카테고리(F-SETUP-03)."""

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


# (키, 이름, 수입 의존도, 납기 요인, 가격 요인, HS 코드). 키는 시연 시드의 ID 생성에 쓴다.
DEFAULT_CATEGORIES: tuple[tuple[str, str, str, list[str], list[str], str], ...] = (
    ("bearing", "베어링", "high", ["FREIGHT", "HOLIDAY_CN"], ["USDKRW"], "8482"),
    ("belt", "V벨트·전동벨트", "medium", ["FREIGHT", "HOLIDAY_KR"], ["USDKRW"], "4010"),
    ("bolt", "볼트·너트", "low", ["HOLIDAY_KR"], [], "7318"),
    ("oil", "절삭유·윤활유", "medium", ["HOLIDAY_KR"], ["USDKRW"], "2710"),
)
