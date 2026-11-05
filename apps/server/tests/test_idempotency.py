import uuid

import pytest
from bjk_server import idempotency
from bjk_server.db.models import Company, IdempotencyKey, User
from bjk_server.errors import ApiError, ErrorCode
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
        users = [User(company_id=c.id, name="test", role="worker") for c in companies]
        s.add_all(users)
        s.flush()
        s.info["users"] = [u.id for u in users]
        yield s
        s.rollback()
    engine.dispose()


def test_first_claim_then_stored_response(session):
    company = session.info["companies"][0]
    user = session.info["users"][0]
    assert (
        idempotency.claim(session, company, "chat_message", "m-1", user, {"text": "hello"}) is None
    )
    idempotency.complete(session, company, "chat_message", "m-1", 200, {"message_id": "x"})

    stored = idempotency.claim(session, company, "chat_message", "m-1", user, {"text": "hello"})
    assert stored == idempotency.StoredResponse(200, {"message_id": "x"})


def test_same_key_in_other_company_or_scope_is_new(session):
    a, b = session.info["companies"]
    user_a, user_b = session.info["users"]
    assert idempotency.claim(session, a, "chat_message", "m-2", user_a, {}) is None
    idempotency.complete(session, a, "chat_message", "m-2", 200, {})

    assert idempotency.claim(session, b, "chat_message", "m-2", user_b, {}) is None
    assert idempotency.claim(session, a, "review_decision", "m-2", user_a, {}) is None


def test_legacy_record_cannot_replay_without_owner_and_request_hash(session):
    company = session.info["companies"][0]
    user = session.info["users"][0]
    session.add(
        IdempotencyKey(
            company_id=company, scope="chat_entry", key="old", status_code=200, response={}
        )
    )
    session.flush()
    with pytest.raises(ApiError) as exc:
        idempotency.claim(session, company, "chat_entry", "old", user, {})
    assert exc.value.code == ErrorCode.IDEMPOTENCY_CONFLICT
