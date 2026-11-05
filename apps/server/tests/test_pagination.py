import uuid
from datetime import UTC, date, datetime

import pytest
from bjk_server.db.models import Company, Part
from bjk_server.errors import ApiError
from bjk_server.pagination import PageParams, decode_cursor, encode_cursor, keyset_page
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session


def test_cursor_round_trip_keeps_types():
    values = [datetime(2026, 11, 4, 10, 0, tzinfo=UTC), date(2026, 11, 4), uuid.uuid4(), 3, "a"]
    assert decode_cursor(encode_cursor(values)) == values


def test_broken_cursor_is_validation_error():
    with pytest.raises(ApiError) as exc:
        decode_cursor("not-a-cursor")
    assert exc.value.status_code == 400


@pytest.fixture
def session(migrated_db_url):
    engine = create_engine(migrated_db_url)
    with Session(engine) as s:
        company = Company(name="t", code=uuid.uuid4().hex[:8])
        s.add(company)
        s.flush()
        s.add_all(Part(company_id=company.id, name=f"부품{i}", unit="개") for i in range(5))
        s.flush()
        s.info["company_id"] = company.id
        yield s
        s.rollback()
    engine.dispose()


def _page(session, cursor, limit=2):
    stmt = select(Part.name, Part.id).where(Part.company_id == session.info["company_id"])
    return keyset_page(
        session,
        stmt,
        [Part.name, Part.id],
        PageParams(cursor=cursor, limit=limit),
        to_item=lambda r: r.name,
        cursor_of=lambda r: [r.name, r.id],
    )


def test_keyset_page_walks_all_rows_once(session):
    seen, cursor = [], None
    while True:
        page = _page(session, cursor)
        seen += page.items
        cursor = page.next_cursor
        if cursor is None:
            break
    assert seen == [f"부품{i}" for i in range(5)]


def test_last_page_has_no_cursor(session):
    assert _page(session, None, limit=5).next_cursor is None
