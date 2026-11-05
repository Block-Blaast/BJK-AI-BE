from typing import Literal

from bjk_contracts import (
    ChatParseRequest,
    ChatParseResponse,
    EmbedRequest,
    EmbedResponse,
    OpinionRequest,
    OpinionResponse,
)
from fastapi import FastAPI, Request
from pydantic import BaseModel

from bjk_ai.chat import parse_chat
from bjk_ai.config import Settings, get_settings
from bjk_ai.embedding import embed_texts
from bjk_ai.gateway import GeminiGateway, LlmGateway
from bjk_ai.opinion import write_opinion


class HealthResponse(BaseModel):
    status: Literal["ok"]
    llm: Literal["ok", "not_configured"]


def create_app(settings: Settings | None = None, gateway: LlmGateway | None = None) -> FastAPI:
    """`gateway`를 넘기지 않으면 API 키가 있을 때만 Gemini에 연결한다."""
    settings = settings or get_settings()
    if gateway is None and settings.llm_configured:
        gateway = GeminiGateway(settings.gemini_api_key)

    app = FastAPI(title="발주콕 ai")
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

    return app


app = create_app()
