"""회사별 LLM 일일 토큰 상한 (API 명세서 1-5).

당일(Asia/Seoul) `llm_calls` 입력·출력 토큰 합계가 회사 설정 `system.llm_daily_tokens` 이상이면
ai를 부르지 않는다. 부르는 쪽은 `quota_exceeded`로 기존 대체 경로를 탄다.
"""

import uuid
from datetime import datetime, time

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bjk_server.auth import set_tenant
from bjk_server.clock import KST, utcnow
from bjk_server.db.models import CompanySettings, LlmCall
from bjk_server.db.session import get_sessionmaker
from bjk_server.defaults import DEFAULT_SETTINGS


def daily_token_limit(db: Session, company_id: uuid.UUID) -> int:
    system = db.scalar(
        select(CompanySettings.system).where(CompanySettings.company_id == company_id)
    )
    default = DEFAULT_SETTINGS["system"]["llm_daily_tokens"]
    return int((system or {}).get("llm_daily_tokens", default))


def tokens_today(db: Session, company_id: uuid.UUID, now: datetime) -> int:
    start = datetime.combine(now.astimezone(KST).date(), time.min, tzinfo=KST)
    total = db.scalar(
        select(func.coalesce(func.sum(LlmCall.input_tokens + LlmCall.output_tokens), 0)).where(
            LlmCall.company_id == company_id, LlmCall.created_at >= start
        )
    )
    return int(total)


def over_daily_quota(db: Session, company_id: uuid.UUID, now: datetime) -> bool:
    return tokens_today(db, company_id, now) >= daily_token_limit(db, company_id)


def check_daily_quota(company_id: uuid.UUID) -> bool:
    """요청 트랜잭션과 따로 읽는다. 같은 요청에서 남긴 기록은 커밋 뒤부터 합계에 든다."""
    with get_sessionmaker().begin() as db:
        set_tenant(db, company_id)
        return over_daily_quota(db, company_id, utcnow())
