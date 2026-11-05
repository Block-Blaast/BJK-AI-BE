"""커서 페이지네이션 (API 명세서 1-3). 응답은 {items, next_cursor}."""

import base64
import json
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any

from fastapi import Query
from pydantic import BaseModel
from sqlalchemy import ColumnElement, Row, Select, tuple_
from sqlalchemy.orm import Session

from bjk_server.errors import ApiError, ErrorCode

DEFAULT_LIMIT = 20
MAX_LIMIT = 100


class Page[T](BaseModel):
    items: list[T]
    next_cursor: str | None


@dataclass(frozen=True)
class PageParams:
    cursor: str | None
    limit: int


def page_params(
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
) -> PageParams:
    return PageParams(cursor=cursor or None, limit=limit)


def _encode_value(value: Any) -> list:
    if isinstance(value, uuid.UUID):
        return ["uuid", str(value)]
    if isinstance(value, datetime):
        return ["dt", value.isoformat()]
    return ["raw", value]


def _decode_value(item: list) -> Any:
    kind, value = item
    if kind == "uuid":
        return uuid.UUID(value)
    if kind == "dt":
        return datetime.fromisoformat(value)
    return value


def encode_cursor(values: Sequence[Any]) -> str:
    raw = json.dumps([_encode_value(v) for v in values], separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> list[Any]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        return [_decode_value(item) for item in json.loads(raw)]
    except (ValueError, TypeError) as exc:
        raise ApiError(ErrorCode.VALIDATION_ERROR, "cursor 값이 올바르지 않습니다.") from exc


def keyset_page[T](
    session: Session,
    stmt: Select,
    keys: Sequence[ColumnElement],
    params: PageParams,
    to_item: Callable[[Row], T],
    cursor_of: Callable[[Row], Sequence[Any]],
    *,
    descending: bool = False,
) -> Page[T]:
    """keys 순서(모두 같은 방향)로 정렬한 한 페이지. 마지막 키는 유일해야 한다.

    cursor_of는 행에서 keys와 같은 순서의 값을 꺼낸다.
    """
    if params.cursor:
        last = decode_cursor(params.cursor)
        if len(last) != len(keys):
            raise ApiError(ErrorCode.VALIDATION_ERROR, "cursor 값이 올바르지 않습니다.")
        row_keys, last_keys = tuple_(*keys), tuple_(*last)
        stmt = stmt.where(row_keys < last_keys if descending else row_keys > last_keys)
    order = [k.desc() for k in keys] if descending else list(keys)
    rows = session.execute(stmt.order_by(*order).limit(params.limit + 1)).all()
    has_more = len(rows) > params.limit
    rows = rows[: params.limit]
    next_cursor = encode_cursor(cursor_of(rows[-1])) if has_more else None
    return Page(items=[to_item(r) for r in rows], next_cursor=next_cursor)
