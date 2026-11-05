"""LLM·임베딩 제공자 연결. 유스케이스는 `LlmGateway`로만 호출해 테스트에서 가짜로 바꿀 수 있다.

- 주 경로는 Amazon Bedrock이다. EC2의 IAM Role로 인증하므로 API 키가 필요 없다(Claude는 Mantle
  Messages API, 임베딩은 Titan Text Embeddings V2).
- Gemini는 API 키가 있을 때만 LLM 재시도용 폴백으로 쓴다. 임베딩은 폴백하지 않는다. 다른 모델의
  벡터끼리는 비교할 수 없기 때문이다.
- 어떤 모델을 쓸지는 게이트웨이가 용도(`LlmPurpose`)를 보고 정하고, 쓴 모델을 결과에 담는다.
"""

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

import boto3
from anthropic import AsyncAnthropicBedrockMantle
from bjk_contracts import EmbedTask, FallbackReason, LlmPurpose, LlmUsage
from google import genai
from google.genai import types
from pydantic import BaseModel, ValidationError

if TYPE_CHECKING:
    from bjk_ai.config import Settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GenerateResult:
    text: str
    input_tokens: int
    output_tokens: int
    model: str


@dataclass(frozen=True)
class EmbedResult:
    vectors: list[list[float]]
    input_tokens: int
    model: str


class LlmGateway(Protocol):
    async def generate_json(
        self,
        *,
        purpose: LlmPurpose,
        system: str,
        prompt: str,
        schema: type[BaseModel],
        max_tokens: int,
        attempt: int,
    ) -> GenerateResult: ...

    async def embed(self, *, texts: list[str], dim: int, task: EmbedTask) -> EmbedResult: ...


class _PerLoopClient:
    """비동기 SDK 클라이언트는 처음 쓴 이벤트 루프에 묶여, 루프가 바뀌면 "Event loop is closed"로
    실패한다. 루프가 바뀌면 새로 만든다(uvicorn은 루프가 하나라 한 번만 만든다).
    """

    def __init__(self, factory: Callable[[], object]) -> None:
        self._factory = factory
        self._client = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def get(self):
        loop = asyncio.get_running_loop()
        if self._client is None or self._loop is not loop:
            self._client = self._factory()
            self._loop = loop
        return self._client


class BedrockGateway:
    """Claude on Amazon Bedrock(Mantle) + Titan Text Embeddings V2. 자격 증명은 AWS 기본 체인."""

    def __init__(
        self,
        *,
        region: str,
        models: Mapping[LlmPurpose, str],
        embedding_model: str,
        effort: str | None = None,
        embed_concurrency: int = 8,
        claude_factory: Callable[[], object] | None = None,
        runtime_client: object | None = None,
    ) -> None:
        self._models = dict(models)
        self._embedding_model = embedding_model
        self._effort = effort
        self._embed_concurrency = embed_concurrency
        self._claude = _PerLoopClient(
            claude_factory or (lambda: AsyncAnthropicBedrockMantle(aws_region=region))
        )
        self._runtime = runtime_client or boto3.client("bedrock-runtime", region_name=region)

    async def generate_json(
        self,
        *,
        purpose: LlmPurpose,
        system: str,
        prompt: str,
        schema: type[BaseModel],
        max_tokens: int,
        attempt: int,
    ) -> GenerateResult:
        model = self._models[purpose]
        extra = {"output_config": {"effort": self._effort}} if self._effort else {}
        response = await self._claude.get().messages.parse(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            output_format=schema,
            **extra,
        )
        if response.stop_reason in ("refusal", "max_tokens"):
            # 거절이나 잘린 응답은 계약에 맞는 JSON이 아니다
            raise RuntimeError(f"bedrock stop_reason={response.stop_reason}")
        text = next((block.text for block in response.content if block.type == "text"), "")
        return GenerateResult(
            text=text,
            input_tokens=response.usage.input_tokens or 0,
            output_tokens=response.usage.output_tokens or 0,
            model=model,
        )

    def _embed_one(self, text: str, dim: int) -> tuple[list[float], int]:
        response = self._runtime.invoke_model(
            modelId=self._embedding_model,
            contentType="application/json",
            accept="application/json",
            body=json.dumps({"inputText": text, "dimensions": dim, "normalize": True}),
        )
        body = json.loads(response["body"].read())
        return body["embedding"], int(body.get("inputTextTokenCount") or 0)

    async def embed(self, *, texts: list[str], dim: int, task: EmbedTask) -> EmbedResult:
        # Titan V2는 한 번에 텍스트 하나만 받는다. boto3는 동기라 스레드에서 몇 개씩 동시에 부른다.
        # 작업 유형(저장용·검색용) 구분이 없어 원문 그대로 보낸다.
        gate = asyncio.Semaphore(self._embed_concurrency)

        async def one(text: str) -> tuple[list[float], int]:
            async with gate:
                return await asyncio.to_thread(self._embed_one, text, dim)

        results = await asyncio.gather(*(one(text.strip()) for text in texts))
        return EmbedResult(
            vectors=[vector for vector, _ in results],
            input_tokens=sum(tokens for _, tokens in results),
            model=self._embedding_model,
        )


# gemini-embedding-2는 task_type 대신 입력 앞의 작업 지시로 용도를 나눈다(Gemini 임베딩 문서).
GEMINI_TASK_FORMATS = {
    EmbedTask.DOCUMENT: "title: none | text: {text}",
    EmbedTask.QUERY: "task: search result | query: {text}",
}


class GeminiGateway:
    def __init__(
        self, api_key: str, *, models: Mapping[LlmPurpose, str], embedding_model: str
    ) -> None:
        self._models = dict(models)
        self._embedding_model = embedding_model
        self._client = _PerLoopClient(lambda: genai.Client(api_key=api_key))

    async def generate_json(
        self,
        *,
        purpose: LlmPurpose,
        system: str,
        prompt: str,
        schema: type[BaseModel],
        max_tokens: int,
        attempt: int,
    ) -> GenerateResult:
        model = self._models[purpose]
        response = await self._client.get().aio.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system,
                response_mime_type="application/json",
                response_schema=schema,
                max_output_tokens=max_tokens,
            ),
        )
        usage = response.usage_metadata
        # 생각(thinking) 토큰도 출력 토큰으로 과금되므로 함께 센다.
        output_tokens = (usage and usage.candidates_token_count) or 0
        output_tokens += (usage and usage.thoughts_token_count) or 0
        return GenerateResult(
            text=response.text or "",
            input_tokens=(usage and usage.prompt_token_count) or 0,
            output_tokens=output_tokens,
            model=model,
        )

    async def embed(self, *, texts: list[str], dim: int, task: EmbedTask) -> EmbedResult:
        # gemini-embedding-2는 문자열 목록을 벡터 하나로 합친다. 텍스트마다 Content로 나눠야
        # 텍스트별 벡터가 나온다.
        contents = [
            types.Content(parts=[types.Part(text=GEMINI_TASK_FORMATS[task].format(text=t.strip()))])
            for t in texts
        ]
        response = await self._client.get().aio.models.embed_content(
            model=self._embedding_model,
            contents=contents,
            config=types.EmbedContentConfig(output_dimensionality=dim),
        )
        return EmbedResult(
            vectors=[list(e.values or []) for e in response.embeddings or []],
            input_tokens=0,
            model=self._embedding_model,
        )


@dataclass
class RoutedGateway:
    """LLM은 첫 시도를 주 제공자로, 재시도는 폴백 제공자(없으면 주 제공자)로 보낸다.

    임베딩은 정한 제공자 하나만 쓴다.
    """

    llm: LlmGateway | None
    embedder: LlmGateway | None
    llm_fallback: LlmGateway | None = None

    async def generate_json(self, *, attempt: int, **kwargs) -> GenerateResult:
        target = self.llm_fallback if attempt > 1 and self.llm_fallback else self.llm
        if target is None:
            raise ProviderUnavailable("llm")
        return await target.generate_json(attempt=attempt, **kwargs)

    async def embed(self, **kwargs) -> EmbedResult:
        if self.embedder is None:
            raise ProviderUnavailable("embedding")
        return await self.embedder.embed(**kwargs)


class ProviderUnavailable(RuntimeError):
    """설정된 제공자를 쓸 수 없음(AWS 자격 증명 없음, Gemini 키 없음)."""


def aws_credentials_available(region: str) -> bool:
    """AWS 기본 자격 증명 체인(환경 변수, 설정 파일, EC2 IAM Role)에서 자격 증명을 찾는다."""
    return boto3.Session(region_name=region).get_credentials() is not None


def build_gateway(
    settings: "Settings",
    *,
    aws_available: Callable[[str], bool] = aws_credentials_available,
) -> RoutedGateway | None:
    """설정에 맞게 제공자를 고른다. 아무것도 쓸 수 없으면 None(모든 요청이 대체 응답).

    LLM은 정한 제공자를 쓸 수 없으면 다른 제공자로 대신하고, 둘 다 있으면 다른 쪽을 재시도 폴백으로
    쓴다. 임베딩은 정한 제공자만 쓴다(server에 저장된 벡터와 같은 모델이어야 하므로).
    """
    providers: dict[str, LlmGateway] = {}
    if aws_available(settings.aws_region):
        providers["bedrock"] = BedrockGateway(
            region=settings.aws_region,
            models={
                LlmPurpose.CHAT_PARSE: settings.bedrock_chat_model,
                LlmPurpose.OPINION: settings.bedrock_opinion_model,
                LlmPurpose.IMPORT_SUGGEST: settings.bedrock_import_model,
            },
            embedding_model=settings.bedrock_embedding_model,
            effort=settings.bedrock_effort,
        )
    if settings.gemini_api_key:
        providers["gemini"] = GeminiGateway(
            settings.gemini_api_key,
            models={
                LlmPurpose.CHAT_PARSE: settings.gemini_chat_model,
                LlmPurpose.OPINION: settings.gemini_opinion_model,
                LlmPurpose.IMPORT_SUGGEST: settings.gemini_import_model,
            },
            embedding_model=settings.gemini_embedding_model,
        )
    if not providers:
        return None
    other = "gemini" if settings.llm_provider == "bedrock" else "bedrock"
    llm = providers.get(settings.llm_provider) or providers.get(other)
    fallback = providers.get(other) if providers.get(settings.llm_provider) else None
    return RoutedGateway(
        llm=llm, llm_fallback=fallback, embedder=providers.get(settings.embedding_provider)
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
    model: str | None = None

    def record(self, result: GenerateResult | EmbedResult) -> None:
        self.input_tokens += result.input_tokens
        self.output_tokens += getattr(result, "output_tokens", 0)
        self.model = result.model


async def call_with_retry[T](
    attempt: Callable[[CallLog], Awaitable[T]], *, budget_seconds: float, max_attempts: int = 2
) -> tuple[T | None, FallbackReason | None, CallLog]:
    """시간 예산 안에서 최대 `max_attempts`번 시도한다(첫 시도 + 1회 재시도).

    `attempt`는 성공하면 결과를, 응답이 계약에 맞지 않으면 `AttemptFailed`를 던진다.
    토큰과 쓴 모델은 `attempt`가 `CallLog.record`로 남긴다. 몇 번째 시도인지는 `log.attempts`.
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


def usage_from(log: CallLog, *, purpose: LlmPurpose, success: bool) -> LlmUsage | None:
    """한 번도 호출하지 못했으면 기록할 사용량이 없다. 모델은 마지막으로 쓴 모델."""
    if log.attempts == 0:
        return None
    return LlmUsage(
        purpose=purpose,
        model=log.model or "unknown",
        input_tokens=log.input_tokens,
        output_tokens=log.output_tokens,
        latency_ms=log.latency_ms,
        attempts=log.attempts,
        success=success,
    )
