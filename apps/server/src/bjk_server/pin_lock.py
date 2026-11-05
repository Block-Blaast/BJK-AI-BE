"""PIN 연속 실패 잠금 (API 명세서 1-5). 같은 계정 5회 연속 실패 시 10분 잠금.

실패 기록은 요청이 오류로 끝나도 남아야 하므로 별도 트랜잭션으로 커밋한다.
"""

import math
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from bjk_server.auth import set_tenant
from bjk_server.db.models import PinAttempt
from bjk_server.errors import ApiError, ErrorCode

MAX_FAILURES = 5
LOCK_MINUTES = 10


def _locked(until: datetime, now: datetime) -> ApiError:
    seconds = math.ceil((until - now).total_seconds())
    return ApiError(
        ErrorCode.PIN_LOCKED,
        f"{LOCK_MINUTES}분 뒤 다시 시도하세요.",
        {"retry_after_seconds": seconds},
        headers={"Retry-After": str(seconds)},
    )


def ensure_not_locked(session: Session, user_id: uuid.UUID, now: datetime) -> None:
    attempt = session.get(PinAttempt, user_id)
    if attempt and attempt.locked_until and attempt.locked_until > now:
        raise _locked(attempt.locked_until, now)


def record_failure(engine: Engine, company_id: uuid.UUID, user_id: uuid.UUID, now: datetime):
    """실패를 1회 기록하고 401(남은 횟수) 또는 423(잠금) 오류를 돌려준다."""
    with Session(engine) as session, session.begin():
        set_tenant(session, company_id)
        attempt = session.scalar(
            select(PinAttempt).where(PinAttempt.user_id == user_id).with_for_update()
        )
        if attempt is None:
            attempt = PinAttempt(user_id=user_id, company_id=company_id, failed_count=0)
            session.add(attempt)
        if attempt.locked_until and attempt.locked_until <= now:
            attempt.locked_until = None
        attempt.failed_count += 1
        attempt.updated_at = now
        if attempt.failed_count >= MAX_FAILURES:
            attempt.failed_count = 0
            attempt.locked_until = now + timedelta(minutes=LOCK_MINUTES)
            return _locked(attempt.locked_until, now)
        remaining = MAX_FAILURES - attempt.failed_count
    return ApiError(
        ErrorCode.INVALID_PIN, "PIN이 맞지 않습니다.", {"remaining_attempts": remaining}
    )


def reset(session: Session, user_id: uuid.UUID) -> None:
    attempt = session.get(PinAttempt, user_id)
    if attempt:
        attempt.failed_count = 0
        attempt.locked_until = None


def utcnow() -> datetime:
    return datetime.now(UTC)
