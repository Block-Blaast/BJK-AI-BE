"""멱등 처리 (API 명세서 1-4).

같은 트랜잭션 안에서 claim → 처리 → complete 순서로 쓴다. 동시에 같은 키가 들어오면
뒤 요청의 INSERT가 앞 트랜잭션 커밋까지 기다린 뒤 저장된 응답을 받는다.
"""

import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from bjk_server.db.models import IdempotencyKey
from bjk_server.errors import ApiError, ErrorCode


@dataclass(frozen=True)
class StoredResponse:
    status_code: int
    body: dict[str, Any]


def claim(
    session: Session,
    company_id: uuid.UUID,
    scope: str,
    key: str,
    user_id: uuid.UUID,
    request: dict[str, Any],
) -> StoredResponse | None:
    """요청자를 확인하고 동일한 요청에만 저장한 응답을 돌려준다."""
    canonical_request = json.dumps(
        request, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    request_hash = hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()
    stmt = (
        insert(IdempotencyKey)
        .values(
            company_id=company_id, scope=scope, key=key, user_id=user_id, request_hash=request_hash
        )
        .on_conflict_do_nothing()
        .returning(IdempotencyKey.key)
    )
    if session.execute(stmt).first() is not None:
        return None
    row = session.get(IdempotencyKey, (company_id, scope, key), populate_existing=True)
    # 소유자와 본문을 알 수 없는 기존 기록도 재생하지 않는다.
    if row is not None and (row.user_id != user_id or row.request_hash != request_hash):
        raise ApiError(ErrorCode.IDEMPOTENCY_CONFLICT, "이미 사용한 요청 식별자입니다.")
    if row is None or row.status_code is None or row.response is None:
        raise RuntimeError("idempotency key claimed but never completed")
    return StoredResponse(row.status_code, row.response)


def complete(
    session: Session,
    company_id: uuid.UUID,
    scope: str,
    key: str,
    status_code: int,
    body: dict[str, Any],
) -> None:
    session.execute(
        update(IdempotencyKey)
        .where(
            IdempotencyKey.company_id == company_id,
            IdempotencyKey.scope == scope,
            IdempotencyKey.key == key,
        )
        .values(status_code=status_code, response=body)
    )
