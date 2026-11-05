"""부품 이름 임베딩 (F-SETUP-02 5단계, F-MATCH-01 4단계)."""

import math

from bjk_contracts import (
    EMBEDDING_DIM,
    AiMeta,
    EmbedRequest,
    EmbedResponse,
    EmbedTask,
    FallbackReason,
    LlmPurpose,
)

from bjk_ai.config import Settings
from bjk_ai.gateway import AttemptFailed, CallLog, LlmGateway, call_with_retry, usage_from

# gemini-embedding-2는 task_type 대신 프롬프트 안의 작업 지시로 용도를 나눈다(Gemini 임베딩 문서).
_TASK_FORMATS = {
    EmbedTask.DOCUMENT: "title: none | text: {text}",
    EmbedTask.QUERY: "task: search result | query: {text}",
}


def format_text(task: EmbedTask, text: str) -> str:
    return _TASK_FORMATS[task].format(text=text.strip())


def _normalize(vector: list[float]) -> list[float]:
    # gemini-embedding-2는 줄인 차원도 정규화해 주지만, 모델이 바뀌어도 기준을 같게 맞춘다.
    norm = math.sqrt(sum(v * v for v in vector))
    if norm == 0:
        raise AttemptFailed(FallbackReason.SCHEMA_INVALID)
    return [v / norm for v in vector]


async def embed_texts(
    request: EmbedRequest, *, gateway: LlmGateway | None, settings: Settings
) -> EmbedResponse:
    if gateway is None:
        return EmbedResponse(
            model=None,
            vectors=None,
            ai=AiMeta(used=False, fallback=True, reason=FallbackReason.ERROR),
        )

    model = settings.gemini_embedding_model
    texts = [format_text(request.task, text) for text in request.texts]

    async def attempt(log: CallLog) -> list[list[float]]:
        result = await gateway.embed(model=model, texts=texts, dim=EMBEDDING_DIM)
        log.input_tokens += result.input_tokens
        if len(result.vectors) != len(texts):
            raise AttemptFailed(FallbackReason.SCHEMA_INVALID)
        if any(len(v) != EMBEDDING_DIM for v in result.vectors):
            raise AttemptFailed(FallbackReason.SCHEMA_INVALID)
        return [_normalize(v) for v in result.vectors]

    vectors, reason, log = await call_with_retry(
        attempt, budget_seconds=settings.embed_budget_seconds
    )
    usage = usage_from(log, purpose=LlmPurpose.EMBEDDING, model=model, success=vectors is not None)
    if vectors is None:
        return EmbedResponse(model=None, vectors=None, ai=AiMeta.failed(reason), usage=usage)
    return EmbedResponse(model=model, vectors=vectors, ai=AiMeta.ok(), usage=usage)
