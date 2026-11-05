"""검토 상세 (API 명세서 REV-02)."""

import uuid

import pytest
from bjk_server.auth import set_tenant
from bjk_server.db.models import Review
from bjk_server.seed.demo import demo_id
from sqlalchemy.orm import Session

from .conftest import auth_header
from .review_rows import SUP_A, add_review


@pytest.fixture
def vbelt(demo_db):
    demo_db.reseed()
    with Session(demo_db.admin) as s, s.begin():
        return add_review(s).id


def _get(client, review_id, user="manager"):
    return client.get(f"/api/v1/reviews/{review_id}", headers=auth_header(user))


def test_vbelt_detail_has_c01_c02_and_no_order_proposal(client, vbelt):
    res = _get(client, vbelt)
    assert res.status_code == 200
    body = res.json()
    codes = {c["code"] for c in body["checks"]}
    assert {"C-01", "C-02"} <= codes
    assert body["verdict"] == "revise" and body["status"] == "reviewed"
    assert body["original"] == {
        "qty": 30,
        "supplier": {"id": SUP_A, "name": "공급사 A"},
        "unit_price": 18000,
        "total": 540000,
    }
    proposal = body["proposal"]
    assert proposal["no_order"] is True and proposal["qty"] == 0
    assert proposal["supplier"] is None and proposal["saving"] == 540000
    assert body["requested_by"] == {
        "type": "user",
        "id": str(demo_id("user", "worker")),
        "name": "이현장",
    }
    assert body["part"] == "V벨트 A-42"
    assert body["opinion"]["source"] == "template"
    snap = body["snapshot"]
    assert snap["hash"].startswith("sha256:")
    assert snap["values"] == {
        "Q": 30,
        "S": 2,
        "O": 10,
        "H_c": 0,
        "H_u": 0,
        "P": 0,
        "m": 1.5,
        "F": 0,
        "D95": 4,
        "D99": 5,
        "R": 0,
        "MOQ": 1,
        "p_mean": 13000.0,
    }
    assert body["computed_at"] == "2026-11-04T03:00:00+09:00"
    assert body["expires_at"] == "2026-11-11T03:00:00+09:00"
    assert body["decision"] is None


def test_worker_sees_own_request_only(client, demo_db, vbelt):
    assert _get(client, vbelt, "worker").status_code == 200
    assert _get(client, vbelt, "worker2").status_code == 404


def test_system_draft_has_no_requester_and_hidden_from_worker(client, demo_db, vbelt):
    with Session(demo_db.admin) as s, s.begin():
        draft = add_review(s, entry="stock_draft").id
    body = _get(client, draft).json()
    assert body["requested_by"] is None and body["entry"] == "stock_draft"
    assert _get(client, draft, "worker").status_code == 404


def test_reviewing_review_has_empty_result(client, demo_db, vbelt):
    with Session(demo_db.admin) as s, s.begin():
        review = s.get(Review, vbelt)
        review.status, review.verdict, review.result, review.opinion = "reviewing", None, None, None
        review.flags = []
    body = _get(client, vbelt).json()
    assert body["status"] == "reviewing" and body["checks"] == []
    assert body["original"] is None and body["proposal"] is None and body["opinion"] is None


def test_unknown_and_other_company_review_is_404(client, demo_db, vbelt):
    assert _get(client, uuid.uuid4()).status_code == 404
    with Session(demo_db.app) as s, s.begin():
        set_tenant(s, uuid.uuid4())
        assert s.get(Review, vbelt) is None


def test_detail_reads_review_saved_by_run_service(client, demo_db):
    """검토 실행 서비스(#146)가 저장한 행을 그대로 읽는다."""
    from bjk_server.jobs import registry  # noqa: F401
    from bjk_server.jobs.runner import run_job

    from .test_review_run import NIGHTLY_AT, _create, _run

    demo_db.reseed()
    demo_db.clear_orders()
    assert run_job(demo_db.app, "nightly", "manual", now=NIGHTLY_AT).status == "ok"
    review_id = _create(demo_db)
    _run(demo_db, review_id)
    body = _get(client, review_id).json()
    assert (body["status"], body["verdict"]) == ("reviewed", "revise")
    assert body["proposal"]["qty"] == 10 and body["proposal"]["basis"] == ["C-01"]
    assert body["snapshot"]["values"]["R"] == 10
    assert body["opinion"]["source"] == "template"
    assert body["part"] == "V벨트 A-42"
