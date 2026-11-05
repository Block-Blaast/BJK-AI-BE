from datetime import UTC, date, datetime, timedelta

import pytest
from bjk_server.config import get_settings
from bjk_server.db.models import CalendarEvent, ExternalIndicator
from bjk_server.external_sources import ExternalData, Holiday
from bjk_server.jobs import nightly as nightly_module
from bjk_server.jobs import registry  # noqa: F401
from bjk_server.jobs.runner import run_job
from bjk_server.seed.demo import COMPANY_CODE, demo_id
from sqlalchemy import select
from sqlalchemy.orm import Session

NOW = datetime(2026, 11, 4, 18, 0, tzinfo=UTC)  # 2026-11-05 03:00 KST
COMPANY = demo_id("company", COMPANY_CODE)


def _weeks(last: date, values: list[float]) -> list[tuple[date, float]]:
    """마지막 월요일까지 주마다 하나씩."""
    n = len(values)
    return [(last - timedelta(weeks=n - 1 - i), v) for i, v in enumerate(values)]


# 평탄하다가 마지막 13주에 크게 오른 운임: 위험도가 높게 나와야 한다.
FREIGHT = _weeks(
    date(2026, 11, 2),
    [3000 + (i % 3) * 10 for i in range(60)] + [3000 + 90 * i for i in range(1, 14)],
)
HOLIDAYS = [
    Holiday("추석", date(2026, 9, 24), date(2026, 9, 26), "KR"),  # 지난 연휴
    Holiday("설날", date(2027, 2, 6), date(2027, 2, 9), "KR"),  # 시드 설날과 겹침
    Holiday("삼일절", date(2027, 3, 1), date(2027, 3, 1), "KR"),
    Holiday("춘절", date(2027, 2, 5), date(2027, 2, 12), "CN"),  # 시드 춘절과 겹침
    Holiday("국경절", date(2027, 10, 1), date(2027, 10, 7), "CN"),
]


@pytest.fixture
def run(demo_db, monkeypatch):
    demo_db.reseed()
    monkeypatch.setenv("EXTERNAL_FETCH", "true")
    get_settings.cache_clear()
    fetched = ExternalData(indicators={"FREIGHT": FREIGHT}, holidays={"KR": [], "CN": []})
    for h in HOLIDAYS:
        fetched.holidays[h.scope].append(h)
    calls = []

    def fake_collect(today):
        calls.append(today)
        return fetched

    monkeypatch.setattr(nightly_module, "collect_external", fake_collect)

    def go():
        result = run_job(demo_db.app, "nightly", "manual", now=NOW)
        assert result.status == "ok", result.error
        return result.summary, calls

    return go


def _series(demo_db, code):
    with Session(demo_db.admin) as s:
        return s.scalars(
            select(ExternalIndicator)
            .where(ExternalIndicator.code == code)
            .order_by(ExternalIndicator.as_of)
        ).all()


def test_fetched_freight_replaces_seed_series(run, demo_db):
    summary, calls = run()
    assert calls == [date(2026, 11, 5)]
    assert summary["external_fetched"] == ["CN", "FREIGHT", "KR"]
    rows = _series(demo_db, "FREIGHT")
    # 받은 기간 안의 시드 CSV 값(다른 출처)은 남지 않는다.
    assert [(r.as_of, r.value) for r in rows] == FREIGHT
    assert rows[-1].level == "high"
    # 받지 못한 환율은 시드 CSV로 채운다.
    assert _series(demo_db, "USDKRW")[-1].as_of == date(2026, 11, 2)


def test_failed_fetch_keeps_previous_values(run, demo_db, monkeypatch):
    run()
    monkeypatch.setattr(nightly_module, "collect_external", lambda today: ExternalData())
    run_job(demo_db.app, "nightly", "manual", now=NOW + timedelta(days=1))
    assert [(r.as_of, r.value) for r in _series(demo_db, "FREIGHT")] == FREIGHT


def test_holidays_added_without_touching_overlaps(run, demo_db):
    summary, _ = run()
    assert summary["holidays_added"] == 2
    with Session(demo_db.admin) as s:
        events = s.scalars(
            select(CalendarEvent)
            .where(CalendarEvent.company_id == COMPANY, CalendarEvent.scope != "supplier")
            .order_by(CalendarEvent.start_date)
        ).all()
    assert [(e.name, e.start_date, e.end_date, e.scope) for e in events] == [
        ("춘절", date(2027, 2, 5), date(2027, 2, 13), "CN"),
        ("설날 연휴", date(2027, 2, 6), date(2027, 2, 9), "KR"),
        ("삼일절", date(2027, 3, 1), date(2027, 3, 1), "KR"),
        ("국경절", date(2027, 10, 1), date(2027, 10, 7), "CN"),
    ]
    # 다시 돌려도 같은 연휴를 두 번 넣지 않는다.
    assert run()[0]["holidays_added"] == 0
