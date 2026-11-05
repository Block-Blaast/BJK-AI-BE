import uuid

import pytest
from bjk_server import idempotency
from bjk_server.db.models import Company
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


@pytest.fixture
def session(migrated_db_url):
    engine = create_engine(migrated_db_url)
    with Session(engine) as s:
        companies = [Company(name=f"c{i}", code=uuid.uuid4().hex[:8]) for i in range(2)]
        s.add_all(companies)
        s.flush()
        s.info["companies"] = [c.id for c in companies]
        yield s
        s.rollback()
    engine.dispose()


def test_first_claim_then_stored_response(session):
    company = session.info["companies"][0]
    assert idempotency.claim(session, company, "chat_message", "m-1") is None
    idempotency.complete(session, company, "chat_message", "m-1", 200, {"message_id": "x"})

    stored = idempotency.claim(session, company, "chat_message", "m-1")
    assert stored == idempotency.StoredResponse(200, {"message_id": "x"})


def test_same_key_in_other_company_or_scope_is_new(session):
    a, b = session.info["companies"]
    assert idempotency.claim(session, a, "chat_message", "m-2") is None
    idempotency.complete(session, a, "chat_message", "m-2", 200, {})

    assert idempotency.claim(session, b, "chat_message", "m-2") is None
    assert idempotency.claim(session, a, "review_decision", "m-2") is None
