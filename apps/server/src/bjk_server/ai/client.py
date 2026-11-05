"""ai 서비스 HTTP 클라이언트 (docs/ai-integration.md 1장).

ai는 LLM이 실패해도 200과 대체 응답을 준다. 연결 거부·시간 초과·계약과 다른 응답처럼 HTTP 자체가
실패하면 AiUnavailable로 알리고, 부르는 쪽이 같은 대체 경로로 간다.
"""

import uuid
from collections.abc import Callable
from functools import lru_cache
from typing import Literal, TypeVar

import httpx
from bjk_contracts import (
    ChatParseRequest,
    ChatParseResponse,
    EmbedRequest,
    EmbedResponse,
    EmbedTask,
    FallbackReason,
    ImportSuggestRequest,
    ImportSuggestResponse,
)
from pydantic import BaseModel, ValidationError

from bjk_server.ai.quota import check_daily_quota
from bjk_server.config import get_settings

# 클라이언트 시간 제한은 ai 쪽 재시도 포함 예산(채팅 2.5초, 임베딩 10초)보다 조금 길게 둔다.
CHAT_TIMEOUT = 3.0
EMBED_TIMEOUT = 12.0
# 채팅 중 부품 표현 하나의 검색용 임베딩. 채팅 응답 3초 목표 안에서 기다린다.
QUERY_EMBED_TIMEOUT = 2.0
# 엑셀 이관 제안. ai는 50줄 묶음을 병렬로 돌리며 묶음마다 30초 예산이다.
IMPORT_TIMEOUT = 35.0
HEALTH_TIMEOUT = 1.0

Response = TypeVar("Response", bound=BaseModel)
LlmStatus = Literal["ok", "not_configured", "error"]


class AiUnavailable(Exception):
    def __init__(self, reason: FallbackReason) -> None:
        super().__init__(reason.value)
        self.reason = reason


# 회사 ID → 일일 토큰 상한을 넘었는지 (bjk_server.ai.quota)
QuotaCheck = Callable[[uuid.UUID], bool]


class AiClient:
    def __init__(self, http: httpx.Client, over_quota: QuotaCheck | None = None) -> None:
        self._http = http
        self._over_quota = over_quota

    def health(self) -> LlmStatus:
        """ai `/health`의 llm 값. 연결하지 못하면 error."""
        try:
            response = self._http.get("/health", timeout=HEALTH_TIMEOUT)
            response.raise_for_status()
            llm = response.json().get("llm")
        except (httpx.HTTPError, ValueError, AttributeError):
            return "error"
        return llm if llm in ("ok", "not_configured") else "error"

    def parse_chat(self, company_id: uuid.UUID, text: str) -> ChatParseResponse:
        body = ChatParseRequest(company_id=company_id, text=text)
        return self._post("/v1/chat/parse", body, ChatParseResponse, CHAT_TIMEOUT)

    def embed(
        self,
        company_id: uuid.UUID,
        task: EmbedTask,
        texts: list[str],
        timeout: float = EMBED_TIMEOUT,
    ) -> EmbedResponse:
        body = EmbedRequest(company_id=company_id, task=task, texts=texts)
        return self._post("/v1/embeddings", body, EmbedResponse, timeout)

    def suggest_import(self, body: ImportSuggestRequest) -> ImportSuggestResponse:
        return self._post("/v1/imports/suggest", body, ImportSuggestResponse, IMPORT_TIMEOUT)

    def _post(
        self, path: str, body: BaseModel, response_model: type[Response], timeout: float
    ) -> Response:
        company_id = getattr(body, "company_id", None)
        if self._over_quota is not None and company_id is not None and self._over_quota(company_id):
            raise AiUnavailable(FallbackReason.QUOTA_EXCEEDED)
        try:
            response = self._http.post(path, json=body.model_dump(mode="json"), timeout=timeout)
            response.raise_for_status()
        except httpx.TimeoutException:
            raise AiUnavailable(FallbackReason.TIMEOUT) from None
        except httpx.HTTPError:
            raise AiUnavailable(FallbackReason.ERROR) from None
        try:
            return response_model.model_validate(response.json())
        except (ValidationError, ValueError):
            raise AiUnavailable(FallbackReason.SCHEMA_INVALID) from None


@lru_cache
def _http_client(base_url: str) -> httpx.Client:
    return httpx.Client(base_url=base_url)


def get_ai_client() -> AiClient | None:
    """설정에 ai 주소가 없으면 None. 부르는 쪽은 ai 없이 대체 경로로 동작한다."""
    base_url = get_settings().ai_base_url
    return AiClient(_http_client(base_url), check_daily_quota) if base_url else None
