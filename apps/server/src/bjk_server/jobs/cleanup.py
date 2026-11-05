"""cleanup 배치: 만료된 호출 제한·PIN 잠금·멱등 키 행 삭제 (매일 04:00).

보관 기간은 명세에 없어 2026-11-05 사용자 결정으로 정했다(#185).
- rate_limits: 창이 끝나고 1시간 지난 행. 가장 긴 창(분 단위)보다 넉넉하다.
- pin_attempts: 잠금이 풀렸고 마지막 실패에서 1일 지난 행. 실패 횟수가 초기화된다.
- idempotency_keys: 만든 지 7일 지난 행. 그 뒤 같은 키를 다시 보내면 새 요청으로 처리한다.
"""

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, or_
from sqlalchemy.orm import Session

from bjk_server.auth import set_tenant
from bjk_server.db.models import IdempotencyKey, PinAttempt, RateLimit
from bjk_server.jobs.runner import company_ids, job

RATE_LIMIT_KEEP = timedelta(hours=1)
PIN_ATTEMPT_KEEP = timedelta(days=1)
IDEMPOTENCY_KEEP = timedelta(days=7)
# 호출 제한 창 중 가장 긴 것. 창 시작 기준으로 이만큼 더 지나야 창이 끝난다.
MAX_RATE_WINDOW = timedelta(hours=1)


@job("cleanup")
def run(session: Session, now: datetime) -> dict[str, Any]:
    rate_limits = session.execute(
        delete(RateLimit).where(RateLimit.window_start < now - MAX_RATE_WINDOW - RATE_LIMIT_KEEP)
    ).rowcount
    pin_attempts = idempotency_keys = 0
    for company_id in company_ids(session):
        set_tenant(session, company_id)
        pin_attempts += session.execute(
            delete(PinAttempt).where(
                PinAttempt.company_id == company_id,
                PinAttempt.updated_at < now - PIN_ATTEMPT_KEEP,
                or_(PinAttempt.locked_until.is_(None), PinAttempt.locked_until < now),
            )
        ).rowcount
        idempotency_keys += session.execute(
            delete(IdempotencyKey).where(
                IdempotencyKey.company_id == company_id,
                IdempotencyKey.created_at < now - IDEMPOTENCY_KEEP,
            )
        ).rowcount
    return {
        "rate_limits": rate_limits,
        "pin_attempts": pin_attempts,
        "idempotency_keys": idempotency_keys,
    }
