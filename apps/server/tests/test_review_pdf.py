import uuid
from datetime import UTC, datetime

import pytest
from bjk_review import ReviewSnapshot as SnapshotValues
from bjk_server.db.models import Review, ReviewSnapshot
from bjk_server.reviews.pdf import stock_projection
from bjk_server.seed.demo import demo_id
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .conftest import auth_header
from .test_review_run import _create, _run, fresh  # noqa: F401

weasyprint = pytest.importorskip("weasyprint", exc_type=OSError)

APPROVED_AT = datetime(2026, 11, 4, 1, 30, tzinfo=UTC)


def _url(review_id) -> str:
    return f"/api/v1/reviews/{review_id}/pdf"


def _approved(db) -> uuid.UUID:
    """승인 API(REV-05) 전이라 승인 상태를 직접 저장한다."""
    review_id = _create(db)
    _run(db, review_id)
    with Session(db.admin) as s, s.begin():
        s.execute(
            update(Review)
            .where(Review.id == review_id)
            .values(
                status="approved",
                decision={"action": "approve_proposal"},
                decided_by=demo_id("user", "owner"),
                decided_at=APPROVED_AT,
            )
        )
    return review_id


def test_approved_review_pdf_is_stable(client, fresh):  # noqa: F811
    review_id = _approved(fresh)
    first = client.get(_url(review_id), headers=auth_header("manager"))
    assert first.status_code == 200, first.text
    assert first.headers["content-type"] == "application/pdf"
    assert first.content.startswith(b"%PDF-")
    again = client.get(_url(review_id), headers=auth_header("owner"))
    assert again.content == first.content


def test_pdf_bytes_do_not_depend_on_render_time(client, fresh, monkeypatch):  # noqa: F811
    """harfbuzz-subset이 없으면(CI, slim 이미지) fontTools가 글꼴을 줄이며 현재 시각을 넣는다."""
    import itertools
    from types import SimpleNamespace

    from fontTools.misc import timeTools
    from weasyprint.pdf import fonts

    monkeypatch.setattr(fonts, "harfbuzz_subset", None)
    ticks = itertools.count(1_800_000_000, 60)
    monkeypatch.setattr(timeTools, "time", SimpleNamespace(time=lambda: next(ticks)))
    review_id = _approved(fresh)
    first = client.get(_url(review_id), headers=auth_header("manager"))
    again = client.get(_url(review_id), headers=auth_header("manager"))
    assert first.status_code == 200, first.text
    assert again.content == first.content


@pytest.mark.parametrize("approve", [False, True])
def test_not_approved_is_409(client, fresh, approve):  # noqa: F811
    review_id = _create(fresh)
    if approve:
        _run(fresh, review_id)  # reviewed지만 아직 승인 전
    res = client.get(_url(review_id), headers=auth_header("manager"))
    assert res.status_code == 409
    assert res.json()["code"] == "PDF_NOT_READY"


def test_worker_is_403_and_unknown_is_404(client, fresh):  # noqa: F811
    review_id = _approved(fresh)
    assert client.get(_url(review_id), headers=auth_header("worker")).status_code == 403
    assert client.get(_url(uuid.uuid4()), headers=auth_header("manager")).status_code == 404


def test_projection_adds_order_on_lead_day(fresh):  # noqa: F811
    review_id = _create(fresh)
    _run(fresh, review_id)
    with Session(fresh.admin) as s:
        values = s.scalar(
            select(ReviewSnapshot.values).where(ReviewSnapshot.review_id == review_id)
        )
    snapshot = SnapshotValues.model_validate(values)
    with_order, without = stock_projection(snapshot, 10, 8)
    assert without[0] == snapshot.stock
    assert with_order[7] == without[7]
    assert with_order[8] == without[8] + 10
