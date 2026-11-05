from datetime import UTC, datetime, timedelta

import pytest
from bjk_server.clock import KST
from bjk_server.db.models import PartMetrics, Review
from bjk_server.jobs import registry  # noqa: F401
from bjk_server.jobs.runner import run_job
from bjk_server.seed.demo import COMPANY_CODE, demo_id
from sqlalchemy import select, update
from sqlalchemy.orm import Session

NIGHTLY_AT = datetime(2026, 11, 3, 18, 0, tzinfo=UTC)  # 2026-11-04 03:00 KST
SCAN_AT = datetime(2026, 11, 3, 22, 0, tzinfo=UTC)  # 07:00 KST
COMPANY = demo_id("company", COMPANY_CODE)


@pytest.fixture
def scanned(demo_db):
    demo_db.reseed()
    assert run_job(demo_db.app, "nightly", "manual", now=NIGHTLY_AT).status == "ok"

    def scan(now=SCAN_AT):
        result = run_job(demo_db.app, "missed-scan", "manual", now=now)
        assert result.status == "ok", result.error
        return result.summary

    yield scan
    demo_db.reseed()


def _expected_parts(demo_db) -> list:
    """F-MISSED-01 대상: P_out ≥ 30%, 마감 ≤ 오늘 + 5일, R > 0. 우선순위 높은 순."""
    today = SCAN_AT.astimezone(KST).date()
    with Session(demo_db.admin) as s:
        return list(
            s.scalars(
                select(PartMetrics.part_id)
                .where(
                    PartMetrics.p_out >= 0.3,
                    PartMetrics.t_deadline <= today + timedelta(days=5),
                    PartMetrics.recommended_qty > 0,
                )
                .order_by(PartMetrics.priority.desc(), PartMetrics.part_id)
            )
        )


def _drafts(demo_db) -> list[Review]:
    with Session(demo_db.admin) as s:
        return list(
            s.scalars(
                select(Review)
                .where(Review.entry == "missed_draft")
                .order_by(Review.created_at, Review.id)
            )
        )


def test_scan_creates_and_reviews_missed_drafts(demo_db, scanned):
    expected = _expected_parts(demo_db)
    assert expected, "시연 시드에 놓친 발주 대상이 있어야 한다"
    assert scanned() == {"companies": 1, "drafts_created": len(expected)}
    drafts = _drafts(demo_db)
    # 한 트랜잭션에서 만들어 생성 시각이 같으므로 순서 대신 대상만 본다
    assert sorted(d.part_id for d in drafts) == sorted(expected)
    with Session(demo_db.admin) as s:
        metrics = {
            m.part_id: m
            for m in s.scalars(select(PartMetrics).where(PartMetrics.part_id.in_(expected)))
        }
    for draft in drafts:
        m = metrics[draft.part_id]
        assert draft.requested_by is None
        assert draft.status in ("reviewed", "held")
        assert draft.request["qty"] == m.recommended_qty
        assert draft.request["supplier_id"] == str(m.default_supplier_id)
        assert draft.opinion["source"] == "template"


def test_rescan_same_day_does_not_duplicate(demo_db, scanned):
    first = scanned()["drafts_created"]
    assert first > 0
    assert scanned()["drafts_created"] == 0
    assert len(_drafts(demo_db)) == first


def test_no_order_closed_today_blocks_new_draft(demo_db, scanned):
    scanned()
    drafts = _drafts(demo_db)
    closed_at = SCAN_AT + timedelta(hours=1)
    with Session(demo_db.admin) as s, s.begin():
        s.execute(
            update(Review)
            .where(Review.id.in_([d.id for d in drafts]))
            .values(
                status="closed",
                decision={"action": "accept_no_order"},
                decided_by=demo_id("user", "owner"),
                decided_at=closed_at,
            )
        )
    assert scanned(SCAN_AT + timedelta(hours=2))["drafts_created"] == 0
    # 다음 날에는 다시 만든다
    assert scanned(SCAN_AT + timedelta(days=1))["drafts_created"] == len(drafts)
