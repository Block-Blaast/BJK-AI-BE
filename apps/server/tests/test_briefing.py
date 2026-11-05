"""아침 브리핑 조회와 briefing 배치 (API 명세서 DSH-01, 14장)."""

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from bjk_server.api import briefing as api
from bjk_server.db.models import (
    AuditFlag,
    Equipment,
    Maintenance,
    Notification,
    PurchaseOrder,
    Review,
    ReviewSnapshot,
)
from bjk_server.jobs.runner import run_job
from bjk_server.seed.demo import COMPANY_CODE, demo_id
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .conftest import auth_header

URL = "/api/v1/briefing/today"
COMPANY = demo_id("company", COMPANY_CODE)
PART = demo_id("part", "6205")
# 2026-11-05 07:30 KST
NOW = datetime(2026, 11, 4, 22, 30, tzinfo=UTC)


@pytest.fixture
def clean(demo_db, monkeypatch):
    """의심 항목·정비 없이 시작한다. 확인할 일이 하나도 없는 상태."""
    demo_db.reseed()
    monkeypatch.setattr(api.clock, "utcnow", lambda: NOW)
    with Session(demo_db.admin) as s, s.begin():
        s.execute(delete(AuditFlag))
        s.execute(delete(Maintenance))


def _review(entry, status="reviewed", loss=0, expires_at=None, requested_by=None):
    return Review(
        id=uuid.uuid4(),
        company_id=COMPANY,
        entry=entry,
        status=status,
        verdict="ok",
        flags=["urgent"] if entry == "missed_draft" else [],
        part_id=PART,
        requested_by=requested_by,
        request={},
        loss=loss,
        expires_at=expires_at,
        created_at=NOW - timedelta(hours=3),
    )


def _get(client, user="manager"):
    return client.get(URL, headers=auth_header(user))


def test_nothing_to_check(client, clean):
    body = _get(client).json()
    assert body["should_notify"] is False
    assert body["missed_orders"] == {"count": 0, "expected_loss_total": 0, "items": []}
    assert body["date"] == "2026-11-05"
    assert _get(client, "worker").status_code == 403


def test_counts_each_item(client, demo_db, clean):
    with Session(demo_db.admin) as s, s.begin():
        small = _review("missed_draft", loss=100)
        big = _review("missed_draft", loss=4_800_000)
        s.add_all([small, big, _review("staff_request", requested_by=demo_id("user", "worker"))])
        s.add(_review("stock_draft", status="approved"))
        s.flush()
        s.add(
            ReviewSnapshot(
                company_id=COMPANY,
                review_id=big.id,
                hash="sha256:x",
                values={"t_deadline": "2026-11-09"},
                settings={},
                computed_at=NOW,
            )
        )
        s.add(
            AuditFlag(
                company_id=COMPANY,
                part_id=PART,
                rule="NEGATIVE_STOCK",
                level="high",
                evidence={},
                keys=["k"],
            )
        )
        for hours in (25, 2):
            s.add(
                PurchaseOrder(
                    company_id=COMPANY,
                    part_id=PART,
                    supplier_id=demo_id("supplier", "a"),
                    qty=10,
                    unit_price=1000,
                    approved_at=NOW - timedelta(hours=hours),
                )
            )
        equipment = s.scalars(select(Equipment.id)).first()
        for day in (date(2026, 11, 3), date(2026, 11, 4)):
            s.add(Maintenance(company_id=COMPANY, equipment_id=equipment, scheduled_date=day))

    body = _get(client).json()
    missed = body["missed_orders"]
    assert missed["count"] == 2 and missed["expected_loss_total"] == 4_800_100
    assert [i["expected_loss"] for i in missed["items"]] == [4_800_000, 100]
    assert missed["items"][0]["t_deadline"] == "2026-11-09"
    assert missed["items"][0]["flags"] == ["urgent"]
    assert body["pending_reviews"] == 1
    assert body["count_needed"] == 1
    assert body["order_check_needed"] == 1
    assert body["maintenance_check_needed"] == 1
    assert body["should_notify"] is True


def test_job_notifies_managers_once_and_expires_reviews(demo_db, clean):
    worker = demo_id("user", "worker")
    with Session(demo_db.admin) as s, s.begin():
        stale = _review("staff_request", expires_at=NOW - timedelta(minutes=1), requested_by=worker)
        fresh = _review("staff_request", expires_at=NOW + timedelta(days=1), requested_by=worker)
        s.add_all([stale, fresh])
        stale_id, fresh_id = stale.id, fresh.id

    first = run_job(demo_db.app, "briefing", "manual", now=NOW)
    assert first.status == "ok", first.error
    assert first.summary == {"reviews_expired": 1, "notifications": 2}
    again = run_job(demo_db.app, "briefing", "manual", now=NOW + timedelta(minutes=5))
    assert again.summary == {"reviews_expired": 0, "notifications": 0}

    with Session(demo_db.admin) as s:
        assert s.get(Review, stale_id).status == "expired"
        assert s.get(Review, fresh_id).status == "reviewed"
        rows = s.scalars(select(Notification)).all()
        briefings = [n for n in rows if n.kind == "briefing"]
        assert {n.user_id for n in briefings} == {
            demo_id("user", "owner"),
            demo_id("user", "manager"),
        }
        assert briefings[0].title == "오늘 확인할 일: 검토 대기 1건"
        [expired] = [n for n in rows if n.kind == "decision_result"]
        assert expired.user_id == worker and expired.target_id == stale_id


def test_job_sends_nothing_when_nothing_to_check(demo_db, clean):
    result = run_job(demo_db.app, "briefing", "manual", now=NOW)
    assert result.summary == {"reviews_expired": 0, "notifications": 0}
