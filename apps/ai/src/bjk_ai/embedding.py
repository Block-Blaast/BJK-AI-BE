"""부품 이름 임베딩 (F-SETUP-02 5단계, F-MATCH-01 4단계).

용도(저장용·검색용)를 입력에 어떻게 반영할지는 제공자마다 달라 게이트웨이가 정한다.
"""

import math

from bjk_contracts import (
    EMBEDDING_DIM,
    AiMeta,
    EmbedRequest,
    EmbedResponse,
    FallbackReason,
    LlmPurpose,
)

from bjk_ai.config import Settings
from bjk_ai.gateway import AttemptFailed, CallLog, LlmGateway, call_with_retry, usage_from


def _normalize(vector: list[float]) -> list[float]:
    # 제공자가 정규화해 주더라도 모델이 바뀌어도 같은 기준(코사인 = 내적)이 되도록 다시 맞춘다.
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

    texts = list(request.texts)

    async def attempt(log: CallLog) -> tuple[str, list[list[float]]]:
        result = await gateway.embed(texts=texts, dim=EMBEDDING_DIM, task=request.task)
        log.record(result)
        if len(result.vectors) != len(texts):
            raise AttemptFailed(FallbackReason.SCHEMA_INVALID)
        if any(len(v) != EMBEDDING_DIM for v in result.vectors):
            raise AttemptFailed(FallbackReason.SCHEMA_INVALID)
        return result.model, [_normalize(v) for v in result.vectors]

    embedded, reason, log = await call_with_retry(
        attempt, budget_seconds=settings.embed_budget_seconds
    )
    usage = usage_from(log, purpose=LlmPurpose.EMBEDDING, success=embedded is not None)
    if embedded is None:
        return EmbedResponse(model=None, vectors=None, ai=AiMeta.failed(reason), usage=usage)
    model, vectors = embedded
    return EmbedResponse(model=model, vectors=vectors, ai=AiMeta.ok(), usage=usage)
