import uuid
from datetime import UTC, datetime, timedelta

import pytest
from bjk_server.domain import hidden_stock as hs

NOW = datetime(2026, 11, 3, 18, 0, tzinfo=UTC)
CATEGORY = uuid.uuid4()
SPEC = {"thread": "M8", "length_mm": 20}


def _part(qty=800, counted_days_ago: float | None = 14, suspect=False) -> hs.HiddenPart:
    counted = NOW - timedelta(days=counted_days_ago) if counted_days_ago is not None else None
    return hs.HiddenPart(uuid.uuid4(), qty, counted, suspect)


@pytest.mark.parametrize(
    ("part", "confirmed"),
    [
        (_part(counted_days_ago=14), True),
        (_part(counted_days_ago=30), True),
        (_part(counted_days_ago=30.01), False),
        (_part(counted_days_ago=None), False),
        (_part(counted_days_ago=1, suspect=True), False),
    ],
)
def test_confirmed_needs_recent_count_and_normal_ledger(part, confirmed):
    assert hs.is_confirmed(part, NOW, 30) is confirmed


def test_split_sums_confirmed_and_unconfirmed():
    recent, old, never = _part(800), _part(300, counted_days_ago=45), _part(5, None)
    hidden = hs.split_hidden([recent, old, never], NOW, 30)
    assert hidden.confirmed == (recent,)
    assert hidden.unconfirmed == (old, never)
    assert (hidden.h_c, hidden.h_u) == (800, 305)


def test_split_skips_parts_without_stock():
    hidden = hs.split_hidden([_part(0), _part(-3, None)], NOW, 30)
    assert hidden == hs.HiddenStock()
    assert (hidden.h_c, hidden.h_u) == (0, 0)


def test_count_days_comes_from_settings():
    part = _part(counted_days_ago=40)
    assert hs.is_confirmed(part, NOW, 30) is False
    assert hs.is_confirmed(part, NOW, 45) is True


@pytest.mark.parametrize(
    ("other_category", "other_spec", "same"),
    [
        (CATEGORY, dict(SPEC), True),
        (CATEGORY, {"thread": "M8", "length_mm": 30}, False),
        (uuid.uuid4(), dict(SPEC), False),
    ],
)
def test_same_spec_needs_same_category_and_spec(other_category, other_spec, same):
    assert hs.same_spec(CATEGORY, SPEC, other_category, other_spec) is same


def test_parts_without_spec_have_no_hidden_stock():
    assert hs.same_spec(CATEGORY, {}, CATEGORY, {}) is False
    assert hs.same_spec(CATEGORY, None, CATEGORY, None) is False
