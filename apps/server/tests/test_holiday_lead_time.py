from datetime import UTC, date, datetime, timedelta

from bjk_server import clock
from bjk_server.db.models import CalendarEvent, PartMetrics
from bjk_server.domain.external import extend_for_holidays
from bjk_server.jobs import registry  # noqa: F401
from bjk_server.jobs.runner import run_job
from bjk_server.seed.demo import demo_id
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .conftest import auth_header

# 2027-02-01 03:00 KST: 설날 연휴(2/6~2/9), 춘절(2/5~2/13)이 납기 구간에 걸친다.
NIGHTLY = datetime(2027, 1, 31, 18, 0, tzinfo=UTC)


def _days(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def test_extend_counts_overlapping_holidays_once():
    today = date(2026, 11, 4)
    assert extend_for_holidays(today, 7, []) == 7
    assert extend_for_holidays(today, 7, [date(2026, 11, 6), date(2026, 11, 6)]) == 8
    # 오늘과 납기 구간 밖 연휴는 세지 않는다.
    assert extend_for_holidays(today, 7, [today, date(2026, 11, 30)]) == 7


def test_extension_reaches_past_long_holiday():
    # 2/2~2/4 사흘 + 춘절 9일 + 2/14~2/17 나흘 = 16일
    cny = _days(date(2027, 2, 5), date(2027, 2, 13))
    assert extend_for_holidays(date(2027, 2, 1), 7, cny) == 16


def _lt90(demo_db, key):
    with Session(demo_db.admin) as s:
        return s.scalar(
            select(PartMetrics.lt90)
            .where(PartMetrics.part_id == demo_id("part", key))
            .order_by(PartMetrics.computed_at.desc())
            .limit(1)
        )


def test_nightly_extends_lead_time_by_category_holidays(demo_db):
    demo_db.reseed()
    assert run_job(demo_db.app, "nightly", "manual", now=NIGHTLY).status == "ok"
    # 볼트(국내 명절, 수입 의존 낮음): 공급사 A 7일 + 설날 4일
    assert _lt90(demo_db, "m820") == 11
    bearing_with_cny = _lt90(demo_db, "6205")

    with Session(demo_db.admin) as s, s.begin():
        s.execute(delete(CalendarEvent))
    assert run_job(demo_db.app, "nightly", "manual", now=NIGHTLY).status == "ok"
    assert _lt90(demo_db, "m820") == 7
    # 베어링은 춘절(9일)이 빠지면 그만큼 짧아진다.
    assert bearing_with_cny - _lt90(demo_db, "6205") == 9


def test_external_status_lists_upcoming_calendar(client, demo_db, monkeypatch):
    demo_db.reseed()
    monkeypatch.setattr(clock, "utcnow", lambda: datetime(2027, 1, 1, 0, 0, tzinfo=UTC))
    body = client.get("/api/v1/external/status", headers=auth_header("manager")).json()
    assert body["upcoming_holidays"] == [
        {"name": "춘절", "start": "2027-02-05", "end": "2027-02-13", "scope": "CN"},
        {"name": "설날 연휴", "start": "2027-02-06", "end": "2027-02-09", "scope": "KR"},
    ]
