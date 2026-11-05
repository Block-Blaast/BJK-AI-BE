"""검토 결정과 발주 생성 (#162, REV-05, F-APPROVAL-01·02·03, F-REVIEW-09)."""

import uuid
from datetime import timedelta

import pytest
from bjk_server import clock
from bjk_server.db.models import (
    Movement,
    Notification,
    PurchaseOrder,
    Review,
    ReviewSnapshot,
    ServerEvent,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .conftest import auth_header
from .test_review_run import A42, NOW, SUPPLIER_A, WORKER, _create, _run, demo_id, fresh  # noqa: F401

MANAGER = demo_id("user", "manager")
OWNER = demo_id("user", "owner")


@pytest.fixture
def at(monkeypatch):
    """결정 시각. 기본은 검토 1시간 뒤(스냅샷 갱신 없음)."""

    def set_now(when):
        monkeypatch.setattr(clock, "utcnow", lambda: when)

    set_now(NOW + timedelta(hours=1))
    return set_now


def _reviewed(db, **kw) -> uuid.UUID:
    review_id = _create(db, **kw)
    assert _run(db, review_id) == "reviewed"
    return review_id


def _hash(db, review_id) -> str:
    with Session(db.admin) as s:
        return s.scalar(
            select(ReviewSnapshot.hash)
            .where(ReviewSnapshot.review_id == review_id)
            .order_by(ReviewSnapshot.created_at.desc())
            .limit(1)
        )


def _decide(client, review_id, body, user="manager", key=None):
    headers = auth_header(user) | {"Idempotency-Key": key or f"k-{uuid.uuid4()}"}
    return client.post(f"/api/v1/reviews/{review_id}/decision", json=body, headers=headers)


def _orders(db, review_id) -> list[PurchaseOrder]:
    with Session(db.admin) as s:
        return list(s.scalars(select(PurchaseOrder).where(PurchaseOrder.review_id == review_id)))


def _review(db, review_id) -> Review:
    with Session(db.admin) as s:
        return s.get(Review, review_id)


def test_approve_proposal_creates_approved_order(client, fresh, at):  # noqa: F811
    review_id = _reviewed(fresh)
    proposal = _review(fresh, review_id).result["proposal"]
    res = _decide(
        client, review_id, {"action": "approve_proposal", "snapshot_hash": _hash(fresh, review_id)}
    )
    assert res.status_code == 201, res.text
    body = res.json()
    po = body["purchase_order"]
    assert (body["status"], body["requester_notified"]) == ("approved", True)
    assert (po["status"], po["qty"], po["supplier"]["id"]) == (
        "approved",
        proposal["qty"],
        proposal["supplier_id"],
    )
    assert po["total"] == po["qty"] * po["unit_price"]
    assert po["saving"] == proposal["saving"]
    assert po["order_message"].startswith("안녕하세요. V벨트 A-42 ")
    assert po["pdf_url"] == f"/api/v1/reviews/{review_id}/pdf"
    [order] = _orders(fresh, review_id)
    assert (order.status, order.approved_by, str(order.id)) == ("approved", MANAGER, po["id"])
    review = _review(fresh, review_id)
    assert (review.status, review.decided_by, review.decision["action"]) == (
        "approved",
        MANAGER,
        "approve_proposal",
    )
    with Session(fresh.admin) as s:
        kinds = s.scalars(select(Notification.kind).where(Notification.user_id == WORKER)).all()
        assert "decision_result" in kinds
        events = s.scalars(
            select(ServerEvent.type).where(ServerEvent.type == "review.decided")
        ).all()
        assert events


def test_approve_original_uses_request(client, fresh, at):  # noqa: F811
    review_id = _reviewed(fresh)
    res = _decide(
        client, review_id, {"action": "approve_original", "snapshot_hash": _hash(fresh, review_id)}
    )
    po = res.json()["purchase_order"]
    assert (po["qty"], po["unit_price"], po["supplier"]["id"], po["saving"]) == (
        30,
        18000,
        str(SUPPLIER_A),
        0,
    )


def test_approve_edited_checks_recheck_hash(client, fresh, at):  # noqa: F811
    review_id = _reviewed(fresh)
    edited = {"qty": 12, "supplier_id": str(SUPPLIER_A), "unit_price": 18000}
    preview = client.post(
        f"/api/v1/reviews/{review_id}/recheck", json=edited, headers=auth_header("manager")
    ).json()
    wrong = _decide(
        client,
        review_id,
        {"action": "approve_edited", "edited": edited, "recheck_hash": "sha256:x"},
    )
    assert wrong.json()["code"] == "SNAPSHOT_REFRESHED"
    res = _decide(
        client,
        review_id,
        {"action": "approve_edited", "edited": edited, "recheck_hash": preview["recheck_hash"]},
    )
    assert res.status_code == 201, res.text
    assert res.json()["purchase_order"]["qty"] == 12


def test_approve_alternative(client, fresh, at):  # noqa: F811
    review_id = _reviewed(fresh)
    alternatives = _review(fresh, review_id).result["alternatives"]
    assert alternatives
    alt = alternatives[0]
    res = _decide(client, review_id, {"action": "approve_alternative", "alternative_id": alt["id"]})
    assert res.status_code == 201, res.text
    po = res.json()["purchase_order"]
    assert (po["qty"], po["unit_price"]) == (alt["qty"], alt["unit_price"])
    bad = _reviewed(fresh)
    assert (
        _decide(
            client, bad, {"action": "approve_alternative", "alternative_id": "nope"}
        ).status_code
        == 400
    )


def test_accept_no_order_closes_without_order(client, fresh, at):  # noqa: F811
    review_id = _reviewed(fresh)
    res = _decide(
        client, review_id, {"action": "accept_no_order", "snapshot_hash": _hash(fresh, review_id)}
    )
    assert res.status_code == 200, res.text
    assert res.json() == {
        "review_id": str(review_id),
        "status": "closed",
        "purchase_order": None,
        "requester_notified": True,
    }
    assert _orders(fresh, review_id) == []


def test_reject_requires_reason(client, fresh, at):  # noqa: F811
    review_id = _reviewed(fresh)
    res = _decide(client, review_id, {"action": "reject"})
    assert (res.status_code, res.json()["code"]) == (422, "REASON_REQUIRED")
    res = _decide(client, review_id, {"action": "reject", "reason": "이번 달 예산 초과"})
    assert res.json()["status"] == "closed"
    with Session(fresh.admin) as s:
        title = s.scalar(select(Notification.title).where(Notification.target_id == review_id))
    assert "이번 달 예산 초과" in title


def test_same_key_replays_and_second_decision_conflicts(client, fresh, at):  # noqa: F811
    review_id = _reviewed(fresh)
    body = {"action": "approve_original", "snapshot_hash": _hash(fresh, review_id)}
    first = _decide(client, review_id, body, key="same")
    again = _decide(client, review_id, body, key="same")
    assert (again.status_code, again.json()) == (first.status_code, first.json())
    other = _decide(client, review_id, body, key="other")
    assert (other.status_code, other.json()["code"]) == (409, "REVIEW_ALREADY_DECIDED")
    assert len(_orders(fresh, review_id)) == 1


def test_missing_idempotency_key_is_400(client, fresh, at):  # noqa: F811
    review_id = _reviewed(fresh)
    res = client.post(
        f"/api/v1/reviews/{review_id}/decision",
        json={"action": "accept_no_order"},
        headers=auth_header("manager"),
    )
    assert res.status_code == 400


def test_manager_cannot_decide_own_request(client, fresh, at):  # noqa: F811
    review_id = _reviewed(fresh, requested_by=MANAGER)
    res = _decide(client, review_id, {"action": "accept_no_order"})
    assert (res.status_code, res.json()["code"]) == (403, "SELF_APPROVAL_NOT_ALLOWED")
    assert (
        _decide(client, review_id, {"action": "accept_no_order"}, user="owner").status_code == 200
    )


def test_held_review_is_not_decidable(client, fresh, at):  # noqa: F811
    review_id = _create(fresh, part_id=None)
    assert _run(fresh, review_id) == "held"
    res = _decide(client, review_id, {"action": "accept_no_order"})
    assert (res.status_code, res.json()["code"]) == (409, "REVIEW_NOT_DECIDABLE")


def test_part_movement_refreshes_snapshot_and_asks_again(client, fresh, at):  # noqa: F811
    review_id = _reviewed(fresh)
    old_hash = _hash(fresh, review_id)
    with Session(fresh.admin) as s, s.begin():
        s.add(
            Movement(
                company_id=demo_id("company", "HS7F3K"),
                part_id=A42,
                type="IN",
                qty=40,
                author_id=WORKER,
                occurred_at=NOW + timedelta(minutes=30),
            )
        )
    res = _decide(client, review_id, {"action": "approve_proposal", "snapshot_hash": old_hash})
    assert (res.status_code, res.json()["code"]) == (409, "SNAPSHOT_REFRESHED")
    detail = res.json()["detail"]
    assert detail["snapshot_hash"] != old_hash and detail["snapshot_hash"] == _hash(
        fresh, review_id
    )
    assert _review(fresh, review_id).status == "reviewed"
    assert _orders(fresh, review_id) == []
    with Session(fresh.admin) as s:
        count = s.scalar(select(func.count()).where(ReviewSnapshot.review_id == review_id))
    assert count == 2
    res = _decide(
        client, review_id, {"action": "accept_no_order", "snapshot_hash": detail["snapshot_hash"]}
    )
    assert res.status_code == 200, res.text


def test_stale_snapshot_hash_asks_again(client, fresh, at):  # noqa: F811
    review_id = _reviewed(fresh)
    res = _decide(client, review_id, {"action": "accept_no_order", "snapshot_hash": "sha256:old"})
    assert res.json()["detail"]["snapshot_hash"] == _hash(fresh, review_id)


def test_worker_cannot_decide(client, fresh, at):  # noqa: F811
    review_id = _reviewed(fresh)
    assert (
        _decide(client, review_id, {"action": "accept_no_order"}, user="worker").status_code == 403
    )
