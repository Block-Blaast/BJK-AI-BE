"""재고 부족 초안 (기능명세서 F-LEDGER-03, CHAT-03 `triggered.draft_review_id`)."""

import uuid
from concurrent.futures import Executor, Future
from datetime import UTC, datetime

import pytest
from bjk_server import clock
from bjk_server.db.models import PartMetrics, PurchaseOrder, Review
from bjk_server.jobs import registry  # noqa: F401
from bjk_server.jobs.runner import run_job
from bjk_server.reviews import drafts
from bjk_server.reviews.service import ReviewRunner
from bjk_server.seed.demo import COMPANY_CODE, demo_id
from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from .conftest import auth_header

COMPANY = demo_id("company", COMPANY_CODE)
P6205 = demo_id("part", "6205")
P20 = demo_id("part", "p20")


class _Inline(Executor):
    def submit(self, fn, /, *args, **kwargs):
        future: Future = Future()
        future.set_result(fn(*args, **kwargs))
        return future


@pytest.fixture
def fresh(demo_db, monkeypatch):
    """오늘 새벽 계산을 마친 시드. 초안 검토는 커밋 직후 같은 스레드에서 돈다(ai 없음)."""
    demo_db.reseed()
    assert run_job(demo_db.app, "nightly", "manual", now=clock.utcnow()).status == "ok"
    scope = sessionmaker(demo_db.app, expire_on_commit=False).begin
    monkeypatch.setattr(drafts, "request_runner", lambda db: ReviewRunner(scope, None, _Inline()))
    yield demo_db
    demo_db.reseed()


def _out(client, part_id, qty=1):
    body = {
        "client_message_id": f"out-{uuid.uuid4()}",
        "type": "OUT",
        "part_id": str(part_id),
        "qty": qty,
    }
    res = client.post("/api/v1/chat/entries", json=body, headers=auth_header("worker"))
    assert res.status_code == 200, res.text
    return res.json()


def _below(client, db, part_id=P6205):
    """재주문점까지 내려가도록 한 번 출고한다."""
    m = _metrics(db, part_id)
    return _out(client, part_id, max(1, m.stock + m.hidden_confirmed - m.reorder_point))


def _metrics(db, part_id) -> PartMetrics:
    with Session(db.admin) as s:
        return s.scalar(select(PartMetrics).where(PartMetrics.part_id == part_id))


def _review(db, review_id) -> Review:
    with Session(db.admin) as s:
        return s.get(Review, review_id)


def test_record_below_reorder_point_creates_draft(client, fresh):
    m = _metrics(fresh, P6205)
    body = _below(client, fresh)
    assert body["stock_after"] + m.hidden_confirmed <= m.reorder_point
    draft_id = body["triggered"]["draft_review_id"]
    assert draft_id is not None
    review = _review(fresh, draft_id)
    assert (review.entry, review.part_id, review.requested_by) == ("stock_draft", P6205, None)
    assert review.request["qty"] == m.recommended_qty
    assert review.request["supplier_id"] == str(m.default_supplier_id)
    assert review.status in ("reviewed", "held")


def test_open_draft_blocks_second_draft(client, fresh):
    assert _below(client, fresh)["triggered"]["draft_review_id"] is not None
    assert _out(client, P6205)["triggered"]["draft_review_id"] is None
    with Session(fresh.admin) as s:
        drafts_made = s.scalars(select(Review).where(Review.entry == "stock_draft")).all()
    assert len(drafts_made) == 1


def test_open_order_blocks_draft(client, fresh):
    with Session(fresh.admin) as s, s.begin():
        s.add(
            PurchaseOrder(
                company_id=COMPANY,
                part_id=P6205,
                supplier_id=demo_id("supplier", "a"),
                qty=10,
                unit_price=18000,
                approved_at=datetime.now(UTC),
            )
        )
    assert _below(client, fresh)["triggered"]["draft_review_id"] is None


def test_no_order_closed_today_blocks_draft(client, fresh):
    first = _below(client, fresh)["triggered"]["draft_review_id"]
    with Session(fresh.admin) as s, s.begin():
        s.execute(
            update(Review)
            .where(Review.id == first)
            .values(
                status="closed",
                decision={"action": "accept_no_order"},
                decided_by=demo_id("user", "owner"),
                decided_at=clock.utcnow(),
            )
        )
    assert _out(client, P6205)["triggered"]["draft_review_id"] is None


def test_above_reorder_point_has_no_draft(client, fresh):
    m = _metrics(fresh, P20)
    body = _out(client, P20)
    assert body["stock_after"] + m.hidden_confirmed > m.reorder_point
    assert body["triggered"]["draft_review_id"] is None


def test_without_nightly_metrics_has_no_draft(client, demo_db, monkeypatch):
    demo_db.reseed()
    monkeypatch.setattr(drafts, "request_runner", lambda db: pytest.fail("초안이 생기면 안 됨"))
    assert _out(client, P6205)["triggered"]["draft_review_id"] is None
