import uuid

from bjk_server.db.models import Review, ReviewSnapshot
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .conftest import auth_header
from .test_review_run import SUPPLIER_A, _create, _run, fresh  # noqa: F401

EDITED = {"qty": 10, "supplier_id": str(SUPPLIER_A), "unit_price": 18000}


def _url(review_id) -> str:
    return f"/api/v1/reviews/{review_id}/recheck"


def _reviewed(db) -> uuid.UUID:
    review_id = _create(db)
    assert _run(db, review_id) == "reviewed"
    return review_id


def _stored(db, review_id):
    with Session(db.admin) as s:
        review = s.get(Review, review_id)
        count = s.scalar(
            select(func.count())
            .select_from(ReviewSnapshot)
            .where(ReviewSnapshot.review_id == review_id)
        )
        return review.result, review.verdict, review.updated_at, count


def test_recheck_previews_edited_values_without_saving(client, fresh):  # noqa: F811
    review_id = _reviewed(fresh)
    before = _stored(fresh, review_id)
    res = client.post(_url(review_id), json=EDITED, headers=auth_header("manager"))
    assert res.status_code == 200, res.text
    body = res.json()
    # 권장량 10개로 고치면 수량 체크가 걸리지 않아 수정안 = 원안
    assert body["verdict"] == "ok"
    assert body["proposal"]["qty"] == 10
    assert body["proposal"]["basis"] == []
    assert body["proposal"]["supplier"] == {"id": str(SUPPLIER_A), "name": "공급사 A"}
    assert "urgent" in body["flags"]
    assert body["recheck_hash"].startswith("sha256:")
    assert _stored(fresh, review_id) == before


def test_same_edit_gives_same_hash(client, fresh):  # noqa: F811
    review_id = _reviewed(fresh)
    first = client.post(_url(review_id), json=EDITED, headers=auth_header("owner")).json()
    again = client.post(_url(review_id), json=EDITED, headers=auth_header("manager")).json()
    other = client.post(
        _url(review_id), json={**EDITED, "qty": 11}, headers=auth_header("manager")
    ).json()
    assert first["recheck_hash"] == again["recheck_hash"]
    assert other["recheck_hash"] != first["recheck_hash"]


def test_original_values_match_stored_review(client, fresh):  # noqa: F811
    review_id = _reviewed(fresh)
    original = {"qty": 30, "supplier_id": str(SUPPLIER_A), "unit_price": 18000}
    body = client.post(_url(review_id), json=original, headers=auth_header("manager")).json()
    with Session(fresh.admin) as s:
        stored = s.scalar(select(ReviewSnapshot.hash).where(ReviewSnapshot.review_id == review_id))
    assert body["recheck_hash"] == stored
    assert body["verdict"] == "revise"


def test_worker_cannot_recheck(client, fresh):  # noqa: F811
    review_id = _reviewed(fresh)
    res = client.post(_url(review_id), json=EDITED, headers=auth_header("worker"))
    assert res.status_code == 403


def test_only_reviewed_status_is_allowed(client, fresh):  # noqa: F811
    held = _create(fresh, part_id=None)
    _run(fresh, held)
    reviewing = _create(fresh)
    for review_id, status in ((held, "held"), (reviewing, "reviewing")):
        res = client.post(_url(review_id), json=EDITED, headers=auth_header("manager"))
        assert res.status_code == 409
        assert res.json()["code"] == "REVIEW_NOT_DECIDABLE"
        assert res.json()["detail"] == {"status": status}


def test_unknown_review_is_404(client, fresh):  # noqa: F811
    res = client.post(_url(uuid.uuid4()), json=EDITED, headers=auth_header("manager"))
    assert res.status_code == 404


def test_invalid_body_is_400(client, fresh):  # noqa: F811
    review_id = _reviewed(fresh)
    res = client.post(_url(review_id), json={"qty": -1}, headers=auth_header("manager"))
    assert res.status_code == 400
