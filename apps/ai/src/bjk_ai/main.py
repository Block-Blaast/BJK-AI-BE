import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

from bjk_contracts import (
    ChatParseRequest,
    ChatParseResponse,
    EmbedRequest,
    EmbedResponse,
    ImportSuggestRequest,
    ImportSuggestResponse,
    OpinionRequest,
    OpinionResponse,
)
from fastapi import FastAPI, Request
from pydantic import BaseModel

from bjk_ai.chat import parse_chat
from bjk_ai.config import Settings, get_settings
from bjk_ai.embedding import embed_texts
from bjk_ai.gateway import LlmGateway, build_gateway
from bjk_ai.import_suggest import suggest_import
from bjk_ai.opinion import write_opinion


class HealthResponse(BaseModel):
    status: Literal["ok"]
    llm: Literal["ok", "not_configured"]


AUTO = "auto"

logger = logging.getLogger(__name__)


async def warm_up(gateway: LlmGateway, timeout: float) -> None:
    """실패해도 서비스는 그대로 뜬다. 첫 요청이 조금 느릴 뿐이다."""
    try:
        await asyncio.wait_for(gateway.warm_up(), timeout=timeout)
    except Exception as exc:
        logger.warning("워밍업 실패: %s", type(exc).__name__)
    else:
        logger.info("워밍업 완료")


def create_app(
    settings: Settings | None = None, gateway: LlmGateway | None | Literal["auto"] = AUTO
) -> FastAPI:
    """`gateway`가 "auto"면 설정과 자격 증명으로 고른다(Bedrock 우선). None이면 미설정."""
    settings = settings or get_settings()
    if gateway == AUTO:
        gateway = build_gateway(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        # 요청과 같은 이벤트 루프에서 데워야 루프별 클라이언트(_PerLoopClient)를 다시 쓴다.
        task = None
        if settings.warm_up and gateway is not None and hasattr(gateway, "warm_up"):
            task = asyncio.create_task(warm_up(gateway, settings.warm_up_timeout_seconds))
        yield
        if task is not None:
            task.cancel()

    app = FastAPI(title="발주콕 ai", lifespan=lifespan)
    app.state.settings = settings
    app.state.gateway = gateway

    @app.get("/health", tags=["health"])
    async def health() -> HealthResponse:
        return HealthResponse(status="ok", llm="ok" if gateway is not None else "not_configured")

    # LLM이 실패해도 200으로 대체 응답을 준다(API 명세서 1-6). 오류는 입력 형식 오류(422)뿐이다.
    @app.post("/v1/chat/parse", tags=["chat"])
    async def chat_parse(body: ChatParseRequest, request: Request) -> ChatParseResponse:
        return await parse_chat(
            body, gateway=request.app.state.gateway, settings=request.app.state.settings
        )

    @app.post("/v1/embeddings", tags=["embedding"])
    async def embeddings(body: EmbedRequest, request: Request) -> EmbedResponse:
        return await embed_texts(
            body, gateway=request.app.state.gateway, settings=request.app.state.settings
        )

    @app.post("/v1/opinions", tags=["review"])
    async def opinions(body: OpinionRequest, request: Request) -> OpinionResponse:
        return await write_opinion(
            body, gateway=request.app.state.gateway, settings=request.app.state.settings
        )

    @app.post("/v1/imports/suggest", tags=["import"])
    async def imports_suggest(
        body: ImportSuggestRequest, request: Request
    ) -> ImportSuggestResponse:
        return await suggest_import(
            body, gateway=request.app.state.gateway, settings=request.app.state.settings
        )

    return app


app = create_app()
