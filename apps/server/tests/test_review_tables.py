import uuid
from datetime import UTC, datetime

import pytest
from alembic import command
from bjk_server.auth import set_tenant
from bjk_server.db.models import Company, Review, ReviewSnapshot
from bjk_server.defaults import default_settings
from bjk_server.seed.demo import COMPANY_CODE, demo_id
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .conftest import alembic_config

COMPANY = demo_id("company", COMPANY_CODE)
WORKER = demo_id("user", "worker")
P6205 = demo_id("part", "6205")


@pytest.fixture
def fresh(demo_db):
    demo_db.reseed()
    yield demo_db
    demo_db.reseed()


def _review(**overrides) -> Review:
    values = {
        "company_id": COMPANY,
        "entry": "staff_request",
        "requested_by": WORKER,
        "part_id": P6205,
        "request": {"qty": 30, "supplier_id": None, "unit_price": None, "text": "베어링 30개"},
    } | overrides
    return Review(**values)


def _app_session(demo_db, company=COMPANY) -> Session:
    session = Session(demo_db.app)
    session.begin()
    set_tenant(session, company)
    return session


def test_review_with_snapshots_round_trip(fresh):
    with _app_session(fresh) as s:
        review = _review()
        s.add(review)
        s.flush()
        assert (review.status, review.verdict, review.flags) == ("reviewing", None, [])
        for n, computed in enumerate([datetime(2026, 11, 4, 3, tzinfo=UTC)] * 2):
            s.add(
                ReviewSnapshot(
                    company_id=COMPANY,
                    review_id=review.id,
                    hash=f"sha256:{n}",
                    values={"S": 3, "D95": 11},
                    settings=default_settings()["review"],
                    computed_at=computed,
                )
            )
            s.flush()
        review.status, review.verdict, review.flags = "reviewed", "revise", ["urgent"]
        review.result = {"checks": [{"code": "C-01", "level": "warning", "facts": {}}]}
        # 커밋하면 회사 지정(SET LOCAL)이 풀려 만료된 속성을 다시 읽지 못하므로 먼저 꺼낸다.
        review_id = review.id
        s.commit()

    with _app_session(fresh) as s:
        saved = s.get(Review, review_id)
        assert (saved.status, saved.verdict, saved.flags) == ("reviewed", "revise", ["urgent"])
        latest = s.scalar(
            select(ReviewSnapshot)
            .where(ReviewSnapshot.review_id == review_id)
            .order_by(ReviewSnapshot.created_at.desc(), ReviewSnapshot.id)
            .limit(1)
        )
        assert latest.settings["c08_days"] == 5


def test_system_draft_has_no_requester(fresh):
    with _app_session(fresh) as s:
        s.add(_review(entry="stock_draft", requested_by=None))
        s.commit()


@pytest.mark.parametrize(
    "overrides",
    [
        {"entry": "manual"},
        {"status": "pending"},
        {"verdict": "maybe"},
        {"flags": ["urgent", "loud"]},
        {"hold_reasons": ["unknown"]},
        {"entry": "staff_request", "requested_by": None},
        {"entry": "missed_draft", "requested_by": WORKER},
        {"decided_at": datetime(2026, 11, 4, tzinfo=UTC)},
    ],
)
def test_constraints_reject_invalid_values(fresh, overrides):
    with _app_session(fresh) as s, pytest.raises(IntegrityError):
        s.add(_review(**overrides))
        s.flush()


def test_other_company_cannot_see_reviews(fresh):
    other = uuid.uuid4()
    with Session(fresh.admin) as s, s.begin():
        s.add(Company(id=other, name="다른회사", code="OTHER4"))
        s.add(_review())
    with _app_session(fresh, other) as s:
        assert s.scalars(select(Review)).all() == []
    with _app_session(fresh) as s:
        assert len(s.scalars(select(Review)).all()) == 1


def test_downgrade_0014_removes_review_tables(empty_db_url):
    config = alembic_config(empty_db_url)
    engine = create_engine(empty_db_url)
    command.upgrade(config, "head")
    command.downgrade(config, "0014")
    assert not {"reviews", "review_snapshots"} & set(inspect(engine).get_table_names())
    command.upgrade(config, "head")
    assert {"reviews", "review_snapshots"} <= set(inspect(engine).get_table_names())
    engine.dispose()
