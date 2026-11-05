"""고정 창 호출 제한 (API 명세서 1-5).

요청이 실패해 롤백돼도 횟수가 남아야 하므로 요청 트랜잭션과 따로 커밋한다.
"""

import math
from datetime import UTC, datetime, timedelta

from sqlalchemy import Engine
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from bjk_server.db.models import RateLimit
from bjk_server.errors import ApiError, ErrorCode


def hit(engine: Engine, bucket: str, limit: int, window_seconds: int, now: datetime | None = None):
    """bucket의 현재 창 호출 수를 1 늘리고, limit을 넘으면 429를 던진다."""
    now = now or utcnow()
    epoch = math.floor(now.timestamp() / window_seconds) * window_seconds
    window_start = datetime.fromtimestamp(epoch, UTC)
    stmt = (
        insert(RateLimit)
        .values(bucket=bucket, window_start=window_start, count=1)
        .on_conflict_do_update(
            index_elements=[RateLimit.bucket, RateLimit.window_start],
            set_={"count": RateLimit.count + 1},
        )
        .returning(RateLimit.count)
    )
    with Session(engine) as session, session.begin():
        count = session.execute(stmt).scalar_one()
    if count > limit:
        retry_after = math.ceil(
            (window_start + timedelta(seconds=window_seconds) - now).total_seconds()
        )
        raise ApiError(
            ErrorCode.RATE_LIMITED,
            "요청이 너무 많습니다. 잠시 후 다시 시도하세요.",
            {"retry_after_seconds": retry_after},
            headers={"Retry-After": str(retry_after)},
        )


def utcnow() -> datetime:
    return datetime.now(UTC)
