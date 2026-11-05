"""SSE 실시간 이벤트 (API 명세서 NOT-03).

화면은 이벤트를 받으면 해당 API를 다시 조회한다. 연결이 끊기면 Last-Event-ID 헤더로 이어 받는다.
연결은 일정 시간 뒤 서버가 닫고, 클라이언트는 retry 간격 뒤 다시 연결한다(토큰 재검증 포함).
"""

import asyncio
import json
import time
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractContextManager
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from bjk_server import events
from bjk_server.auth import CurrentUser, set_tenant
from bjk_server.db.session import get_session_scope

router = APIRouter(tags=["events"])

POLL_SECONDS = 2.0
KEEPALIVE_SECONDS = 15.0
# 이 시간이 지나면 서버가 연결을 닫는다. 프록시 유휴 시간 초과를 피하고 토큰을 다시 검증한다.
MAX_STREAM_SECONDS = 300.0
RETRY_MILLISECONDS = 3000

SessionScope = Annotated[Callable[[], AbstractContextManager[Session]], Depends(get_session_scope)]


def _format(row: events.EventRow) -> str:
    data = json.dumps(row.data, ensure_ascii=False, separators=(",", ":"))
    return f"id: {row.id}\nevent: {row.type}\ndata: {data}\n\n"


def _parse_last_event_id(value: str | None) -> int | None:
    if value is None or not value.strip().isdigit():
        return None
    return int(value.strip())


@router.get("/events")
async def stream_events(
    request: Request,
    user: CurrentUser,
    open_session: SessionScope,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    """NOT-03. 같은 회사의 이벤트를 SSE로 보낸다. Last-Event-ID가 없으면 연결 이후 이벤트부터."""

    def query(fn, *args):
        with open_session() as session:
            set_tenant(session, user.company_id)
            return fn(session, *args)

    start = _parse_last_event_id(last_event_id)
    if start is None:
        start = await run_in_threadpool(query, events.latest_id)

    async def body() -> AsyncIterator[str]:
        cursor = start
        sent: dict[int, float] = {}
        began = last_write = time.monotonic()
        yield f"retry: {RETRY_MILLISECONDS}\n\n"
        while time.monotonic() - began < MAX_STREAM_SECONDS:
            if await request.is_disconnected():
                return
            rows = await run_in_threadpool(query, events.read_after, cursor)
            now = time.monotonic()
            for row in rows:
                # 재연결 직후 범위(start 이하)와 이미 보낸 이벤트는 건너뛴다.
                if row.id <= start or row.id in sent:
                    continue
                sent[row.id] = now
                cursor = max(cursor, row.id)
                last_write = now
                yield _format(row)
            window = events.LATE_COMMIT_WINDOW_SECONDS * 2
            sent = {k: v for k, v in sent.items() if now - v < window}
            if now - last_write >= KEEPALIVE_SECONDS:
                last_write = now
                yield ": keepalive\n\n"
            await asyncio.sleep(POLL_SECONDS)

    return StreamingResponse(
        body(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
