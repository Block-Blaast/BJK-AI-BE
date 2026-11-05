"""멱등 처리 (API 명세서 1-4).

같은 트랜잭션 안에서 claim → 처리 → complete 순서로 쓴다. 동시에 같은 키가 들어오면
뒤 요청의 INSERT가 앞 트랜잭션 커밋까지 기다린 뒤 저장된 응답을 받는다.
"""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from bjk_server.db.models import IdempotencyKey


@dataclass(frozen=True)
class StoredResponse:
    status_code: int
    body: dict[str, Any]


def claim(session: Session, company_id: uuid.UUID, scope: str, key: str) -> StoredResponse | None:
    """키를 선점한다. 이미 처리한 키면 저장한 응답을 돌려준다."""
    stmt = (
        insert(IdempotencyKey)
        .values(company_id=company_id, scope=scope, key=key)
        .on_conflict_do_nothing()
        .returning(IdempotencyKey.key)
    )
    if session.execute(stmt).first() is not None:
        return None
    row = session.get(IdempotencyKey, (company_id, scope, key), populate_existing=True)
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
