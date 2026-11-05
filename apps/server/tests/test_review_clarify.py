import uuid

import pytest
from bjk_server.db.models import Company, Part, Review, ReviewSnapshot, ServerEvent
from bjk_server.reviews.service import ReviewRunner, get_review_runner
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .conftest import auth_header, build_client
from .test_review_run import A42, SUPPLIER_A, _create, _Inline, _run, _scope, fresh  # noqa: F401


@pytest.fixture
def api(fresh):  # noqa: F811
    client = build_client(fresh)
    runner = ReviewRunner(_scope(fresh), None, _Inline())
    client.app.dependency_overrides[get_review_runner] = lambda: runner
    return client


def _url(review_id) -> str:
    return f"/api/v1/reviews/{review_id}/clarify"


def _held(db) -> uuid.UUID:
    review_id = _create(db, part_id=None)
    assert _run(db, review_id) == "held"
    return review_id


def _review(db, review_id) -> Review:
    with Session(db.admin) as s:
        return s.get(Review, review_id)


def test_part_clarify_reruns_same_review(api, fresh):  # noqa: F811
    review_id = _held(fresh)
    res = api.post(_url(review_id), json={"part_id": str(A42)}, headers=auth_header("worker"))
    assert res.status_code == 202, res.text
    assert res.json() == {"review_id": str(review_id), "status": "reviewing"}
    review = _review(fresh, review_id)
    assert (review.status, review.verdict, review.part_id) == ("reviewed", "revise", A42)
    assert review.hold_reasons == []
    with Session(fresh.admin) as s:
        snapshots = s.scalar(
            select(func.count())
            .select_from(ReviewSnapshot)
            .where(ReviewSnapshot.review_id == review_id)
        )
        steps = s.scalars(
            select(ServerEvent.data["step"].astext).where(
                ServerEvent.type == "review.progress",
                ServerEvent.data["review_id"].astext == str(review_id),
            )
        ).all()
    assert snapshots == 2  # 보류 때 스냅샷 + 보완 후 스냅샷
    assert steps.count("done") == 2


def test_supplier_clarify_updates_request(api, fresh):  # noqa: F811
    review_id = _held(fresh)
    body = {"part_id": str(A42), "supplier_id": str(SUPPLIER_A)}
    assert api.post(_url(review_id), json=body, headers=auth_header("manager")).status_code == 202
    assert _review(fresh, review_id).request["supplier_id"] == str(SUPPLIER_A)


def test_reviewed_review_cannot_be_clarified(api, fresh):  # noqa: F811
    review_id = _create(fresh)
    _run(fresh, review_id)
    res = api.post(_url(review_id), json={"part_id": str(A42)}, headers=auth_header("manager"))
    assert res.status_code == 409
    assert res.json()["code"] == "REVIEW_NOT_DECIDABLE"
    assert res.json()["detail"] == {"status": "reviewed"}


def test_other_worker_gets_404(api, fresh):  # noqa: F811
    review_id = _held(fresh)
    res = api.post(_url(review_id), json={"part_id": str(A42)}, headers=auth_header("worker2"))
    assert res.status_code == 404
    assert _review(fresh, review_id).status == "held"


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({}, None),
        ({"part_id": str(uuid.uuid4())}, "part_id"),
        ({"supplier_id": str(uuid.uuid4())}, "supplier_id"),
    ],
)
def test_invalid_values_are_400(api, fresh, body, field):  # noqa: F811
    review_id = _held(fresh)
    res = api.post(_url(review_id), json=body, headers=auth_header("worker"))
    assert res.status_code == 400
    if field:
        assert res.json()["detail"] == {"field": field}
    assert _review(fresh, review_id).status == "held"


def test_other_company_part_is_400(api, fresh):  # noqa: F811
    other = uuid.uuid4()
    with Session(fresh.admin) as s, s.begin():
        s.add(Company(id=other, name="다른회사", code="OTHER5"))
        s.flush()
        part = Part(company_id=other, name="볼베어링 6205ZZ", unit="개")
        s.add(part)
        s.flush()
        part_id = part.id
    review_id = _held(fresh)
    res = api.post(_url(review_id), json={"part_id": str(part_id)}, headers=auth_header("worker"))
    assert res.status_code == 400
