import uuid
from concurrent.futures import Executor, Future
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from bjk_review import PROGRESS_STEPS, OrderRequest
from bjk_server.auth import set_tenant
from bjk_server.db.models import LlmCall, Review, ReviewSnapshot, ServerEvent
from bjk_server.defaults import default_settings
from bjk_server.jobs import registry  # noqa: F401
from bjk_server.jobs.runner import run_job
from bjk_server.reviews.service import (
    ReviewRunner,
    create_review,
    review_settings,
    run_review,
)
from bjk_server.seed.demo import COMPANY_CODE, demo_id
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from .ai_fakes import FakeAi

NIGHTLY_AT = datetime(2026, 11, 3, 18, 0, tzinfo=UTC)  # 2026-11-04 03:00 KST
NOW = datetime(2026, 11, 4, 0, 40, tzinfo=UTC)  # 09:40 KST
COMPANY = demo_id("company", COMPANY_CODE)
A42 = demo_id("part", "a42")
SUPPLIER_A = demo_id("supplier", "a")
WORKER = demo_id("user", "worker")


@pytest.fixture
def fresh(demo_db):
    demo_db.reseed()
    # 명세 예시(F-REVIEW-10) 숫자를 확인하므로 시드 발주 이력 없이 기본 납기로 계산한다
    demo_db.clear_orders()
    result = run_job(demo_db.app, "nightly", "manual", now=NIGHTLY_AT)
    assert result.status == "ok", result.error
    yield demo_db
    demo_db.reseed()


def _scope(db):
    return sessionmaker(db.app, expire_on_commit=False).begin


def _create(db, part_id=A42, qty=30, supplier_id=SUPPLIER_A, unit_price=18000, **kw) -> uuid.UUID:
    order = OrderRequest(
        qty=qty, supplier_id=str(supplier_id) if supplier_id else None, unit_price=unit_price
    )
    with _scope(db)() as s:
        set_tenant(s, COMPANY)
        kw.setdefault("entry", "staff_request")
        kw.setdefault("requested_by", WORKER if kw["entry"] == "staff_request" else None)
        return create_review(s, COMPANY, order=order, part_id=part_id, **kw).id


def _run(db, review_id, ai=None):
    return run_review(_scope(db), ai, COMPANY, review_id, now=lambda: NOW)


def _review(db, review_id) -> Review:
    with Session(db.admin) as s:
        return s.get(Review, review_id)


def _events(db, review_id) -> list[tuple[str, dict]]:
    with Session(db.admin) as s:
        rows = s.execute(select(ServerEvent.type, ServerEvent.data).order_by(ServerEvent.id))
        return [(t, d) for t, d in rows if d.get("review_id") == str(review_id)]


def test_vbelt_30_is_revised_down(fresh):
    review_id = _create(fresh)
    assert _run(fresh, review_id) == "reviewed"
    review = _review(fresh, review_id)
    assert (review.status, review.verdict) == ("reviewed", "revise")
    assert review.flags == ["urgent", "alternative"]
    proposal = review.result["proposal"]
    # 열린 발주(O) 연결 전이라 R = D95 − S = 10. O 10개가 들어오면 수정안은 0개가 된다.
    assert (proposal["qty"], proposal["basis"]) == (10, ["C-01"])
    assert review.original_total == 540000
    assert review.saving == 540000 - proposal["total"]
    assert review.expires_at == NOW + timedelta(days=7)
    with Session(fresh.admin) as s:
        snapshot = s.scalar(select(ReviewSnapshot).where(ReviewSnapshot.review_id == review_id))
    assert snapshot.values["part_id"] == str(A42)
    assert snapshot.values["stock"] == 2
    assert snapshot.settings == review_settings(default_settings()).model_dump(mode="json")
    assert snapshot.hash.startswith("sha256:")


def test_unresolved_part_is_held(fresh):
    review_id = _create(fresh, part_id=None)
    assert _run(fresh, review_id) == "held"
    review = _review(fresh, review_id)
    assert review.verdict == "hold"
    # 부품을 모르면 그 부품의 공급사 조건도 없어 공급사 미특정이 함께 붙는다
    assert review.hold_reasons == ["part_unresolved", "supplier_unresolved"]
    assert review.part_id is None
    assert review.expires_at == NOW + timedelta(days=7)
    assert review.opinion["source"] == "template"


def test_without_ai_uses_template_opinion(fresh):
    review_id = _create(fresh)
    _run(fresh, review_id, ai=None)
    opinion = _review(fresh, review_id).opinion
    assert opinion["source"] == "template"
    assert opinion["verified"] is True
    assert opinion["text"].startswith("[수정 권고 · 긴급 · 대안]")


def test_ai_opinion_is_saved_with_usage(fresh):
    ai = FakeAi()
    review_id = _create(fresh)
    _run(fresh, review_id, ai=ai.client())
    assert ai.paths() == ["/v1/opinions"]
    assert _review(fresh, review_id).opinion["source"] == "llm"
    with Session(fresh.admin) as s:
        calls = s.scalars(select(LlmCall).where(LlmCall.company_id == COMPANY)).all()
    assert [c.purpose for c in calls] == ["opinion"]


@pytest.mark.parametrize("fail", [httpx.ConnectError("down"), 500])
def test_ai_failure_falls_back_to_template(fresh, fail):
    review_id = _create(fresh)
    assert _run(fresh, review_id, ai=FakeAi(fail=fail).client()) == "reviewed"
    assert _review(fresh, review_id).opinion["source"] == "template"


def test_events_arrive_in_step_order(fresh):
    review_id = _create(fresh)
    _run(fresh, review_id)
    events = _events(fresh, review_id)
    assert events[0] == ("review.created", {"review_id": str(review_id), "entry": "staff_request"})
    steps = [d["step"] for t, d in events[1:]]
    assert {t for t, _ in events[1:]} == {"review.progress"}
    assert steps == list(PROGRESS_STEPS)
    assert events[-1][1]["at"] == "2026-11-04T09:40:00+09:00"


def test_held_review_skips_check_steps(fresh):
    review_id = _create(fresh, part_id=None)
    _run(fresh, review_id)
    steps = [d["step"] for t, d in _events(fresh, review_id) if t == "review.progress"]
    assert steps == [s for s in PROGRESS_STEPS if s not in ("checks", "proposal")]


def test_other_open_request_counts_as_p(fresh):
    first = _create(fresh, qty=3)
    _run(fresh, first)
    second = _create(fresh, qty=3)
    _run(fresh, second)
    with Session(fresh.admin) as s:
        values = s.scalar(select(ReviewSnapshot.values).where(ReviewSnapshot.review_id == second))
    first_qty = _review(fresh, first).result["proposal"]["qty"]
    assert values["open_requests"] == [{"review_id": str(first), "qty": first_qty}]


def test_run_is_skipped_when_not_reviewing(fresh):
    review_id = _create(fresh)
    _run(fresh, review_id)
    assert _run(fresh, review_id) is None


class _Inline(Executor):
    def submit(self, fn, /, *args, **kwargs):
        future: Future = Future()
        future.set_result(fn(*args, **kwargs))
        return future


def test_runner_starts_after_commit_only(fresh):
    runner = ReviewRunner(_scope(fresh), None, _Inline())
    order = OrderRequest(qty=30, supplier_id=str(SUPPLIER_A), unit_price=18000)
    with _scope(fresh)() as s:
        set_tenant(s, COMPANY)
        committed = create_review(
            s, COMPANY, entry="staff_request", order=order, part_id=A42, requested_by=WORKER
        ).id
        runner.start_after_commit(s, COMPANY, committed)
    assert _review(fresh, committed).status == "reviewed"

    with pytest.raises(RuntimeError), _scope(fresh)() as s:
        set_tenant(s, COMPANY)
        rolled_back = create_review(
            s, COMPANY, entry="staff_request", order=order, part_id=A42, requested_by=WORKER
        ).id
        runner.start_after_commit(s, COMPANY, rolled_back)
        raise RuntimeError
    assert _review(fresh, rolled_back) is None


def test_system_draft_without_supplier_uses_default(fresh):
    review_id = _create(fresh, entry="stock_draft", qty=10, supplier_id=None, unit_price=None)
    assert _run(fresh, review_id) == "reviewed"
    review = _review(fresh, review_id)
    assert review.requested_by is None
    assert review.result["original"]["supplier_id"] == str(SUPPLIER_A)
