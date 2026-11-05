"""LLM 제공자 연결. 유스케이스는 `LlmGateway`로만 호출해 테스트에서 가짜로 바꿀 수 있다."""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from bjk_contracts import FallbackReason, LlmPurpose, LlmUsage
from google import genai
from google.genai import types
from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GenerateResult:
    text: str
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class EmbedResult:
    vectors: list[list[float]]
    input_tokens: int


class LlmGateway(Protocol):
    async def generate_json(
        self, *, model: str, system: str, prompt: str, schema: type[BaseModel]
    ) -> GenerateResult: ...

    async def embed(self, *, model: str, texts: list[str], dim: int) -> EmbedResult: ...


class GeminiGateway:
    def __init__(self, api_key: str) -> None:
        self._client = genai.Client(api_key=api_key)

    async def generate_json(
        self, *, model: str, system: str, prompt: str, schema: type[BaseModel]
    ) -> GenerateResult:
        response = await self._client.aio.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system,
                response_mime_type="application/json",
                response_schema=schema,
            ),
        )
        usage = response.usage_metadata
        return GenerateResult(
            text=response.text or "",
            input_tokens=(usage and usage.prompt_token_count) or 0,
            output_tokens=(usage and usage.candidates_token_count) or 0,
        )

    async def embed(self, *, model: str, texts: list[str], dim: int) -> EmbedResult:
        # gemini-embedding-2는 문자열 목록을 벡터 하나로 합친다. 텍스트마다 Content로 나눠야
        # 텍스트별 벡터가 나온다.
        response = await self._client.aio.models.embed_content(
            model=model,
            contents=[types.Content(parts=[types.Part(text=text)]) for text in texts],
            config=types.EmbedContentConfig(output_dimensionality=dim),
        )
        return EmbedResult(
            vectors=[list(e.values or []) for e in response.embeddings or []],
            input_tokens=0,
        )


class AttemptFailed(Exception):
    def __init__(self, reason: FallbackReason) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass
class CallLog:
    attempts: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0


async def call_with_retry[T](
    attempt: Callable[[CallLog], Awaitable[T]], *, budget_seconds: float, max_attempts: int = 2
) -> tuple[T | None, FallbackReason | None, CallLog]:
    """시간 예산 안에서 최대 `max_attempts`번 시도한다(첫 시도 + 1회 재시도).

    `attempt`는 성공하면 결과를, 응답이 계약에 맞지 않으면 `AttemptFailed`를 던진다.
    토큰은 `attempt`가 `CallLog`에 더한다.
    """
    log = CallLog()
    started = time.monotonic()
    reason: FallbackReason = FallbackReason.ERROR
    while log.attempts < max_attempts:
        remaining = budget_seconds - (time.monotonic() - started)
        if remaining <= 0:
            reason = FallbackReason.TIMEOUT
            break
        log.attempts += 1
        try:
            result = await asyncio.wait_for(attempt(log), timeout=remaining)
        except TimeoutError:
            reason = FallbackReason.TIMEOUT
        except AttemptFailed as exc:
            reason = exc.reason
        except ValidationError:
            reason = FallbackReason.SCHEMA_INVALID
        except Exception as exc:
            # 제공자 오류 메시지에는 요청 내용이 섞일 수 있어 종류만 남긴다.
            logger.warning("LLM 호출 실패: %s", type(exc).__name__)
            reason = FallbackReason.ERROR
        else:
            log.latency_ms = int((time.monotonic() - started) * 1000)
            return result, None, log
    log.latency_ms = int((time.monotonic() - started) * 1000)
    return None, reason, log


def usage_from(log: CallLog, *, purpose: LlmPurpose, model: str, success: bool) -> LlmUsage | None:
    """한 번도 호출하지 못했으면 기록할 사용량이 없다."""
    if log.attempts == 0:
        return None
    return LlmUsage(
        purpose=purpose,
        model=model,
        input_tokens=log.input_tokens,
        output_tokens=log.output_tokens,
        latency_ms=log.latency_ms,
        attempts=log.attempts,
        success=success,
    )
