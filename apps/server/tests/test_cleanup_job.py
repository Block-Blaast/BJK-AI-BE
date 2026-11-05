"""cleanup 배치: 만료 행만 지운다 (#185)."""

from datetime import UTC, datetime, timedelta

from bjk_server.db.models import IdempotencyKey, PinAttempt, RateLimit
from bjk_server.jobs.runner import run_job
from bjk_server.seed.demo import COMPANY_CODE, demo_id
from sqlalchemy import select
from sqlalchemy.orm import Session

NOW = datetime(2026, 11, 4, 19, 0, tzinfo=UTC)
COMPANY = demo_id("company", COMPANY_CODE)


def _seed(s):
    s.add_all(
        [
            RateLimit(bucket="chat:old", window_start=NOW - timedelta(hours=3), count=5),
            RateLimit(bucket="chat:new", window_start=NOW - timedelta(minutes=30), count=5),
            IdempotencyKey(
                company_id=COMPANY, scope="chat", key="old", created_at=NOW - timedelta(days=8)
            ),
            IdempotencyKey(
                company_id=COMPANY, scope="chat", key="new", created_at=NOW - timedelta(days=6)
            ),
            # 잠금 해제·실패 1일 지남 → 삭제
            PinAttempt(
                user_id=demo_id("user", "worker"),
                company_id=COMPANY,
                failed_count=5,
                locked_until=NOW - timedelta(days=2),
                updated_at=NOW - timedelta(days=2),
            ),
            # 아직 잠김 → 유지
            PinAttempt(
                user_id=demo_id("user", "worker2"),
                company_id=COMPANY,
                failed_count=5,
                locked_until=NOW + timedelta(minutes=5),
                updated_at=NOW - timedelta(days=2),
            ),
        ]
    )


def test_cleanup_deletes_only_expired_rows(demo_db):
    demo_db.reseed()
    with Session(demo_db.admin) as s, s.begin():
        _seed(s)

    result = run_job(demo_db.app, "cleanup", "manual", now=NOW)

    assert result.status == "ok", result.error
    assert result.summary == {"rate_limits": 1, "pin_attempts": 1, "idempotency_keys": 1}
    with Session(demo_db.admin) as s:
        assert set(s.scalars(select(RateLimit.bucket))) >= {"chat:new"}
        assert "chat:old" not in set(s.scalars(select(RateLimit.bucket)))
        assert set(s.scalars(select(IdempotencyKey.key))) == {"new"}
        assert set(s.scalars(select(PinAttempt.user_id))) == {demo_id("user", "worker2")}
