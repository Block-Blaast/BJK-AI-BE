"""부품 이름 임베딩 (F-SETUP-02 5단계, F-MATCH-01 4단계) server → ai 계약.

벡터 저장(pgvector)과 코사인 비교는 server가 한다. ai는 벡터만 만든다.
"""

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from bjk_contracts.common import AiMeta, LlmUsage

EMBEDDING_DIM = 1024
EMBED_MAX_TEXTS = 100
EMBED_TEXT_MAX_LEN = 500


class EmbedTask(StrEnum):
    """저장용과 검색용을 나눈다. 같은 용도끼리 만든 벡터만 비교 기준이 같다.

    - `document`: 부품 이름·별칭을 등록할 때(`parts`, `part_aliases`에 저장)
    - `query`: 채팅의 부품 표현으로 후보를 찾을 때(저장하지 않음)
    """

    DOCUMENT = "document"
    QUERY = "query"


class EmbedRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    company_id: UUID
    task: EmbedTask
    texts: list[str] = Field(min_length=1, max_length=EMBED_MAX_TEXTS)

    @model_validator(mode="after")
    def _texts_not_blank(self) -> "EmbedRequest":
        for text in self.texts:
            if not text.strip() or len(text) > EMBED_TEXT_MAX_LEN:
                raise ValueError(f"texts는 1~{EMBED_TEXT_MAX_LEN}자의 비어 있지 않은 문자열이다")
        return self


class EmbedResponse(BaseModel):
    """`vectors[i]`는 `texts[i]`의 벡터. 길이는 `EMBEDDING_DIM`이고 L2 정규화돼 있다.

    `model`이 바뀌면 이전 벡터와 비교할 수 없으므로 server는 벡터와 함께 저장한다.
    실패하면 `vectors`는 None이고 `ai.fallback`이 True다.
    """

    model_config = ConfigDict(frozen=True)

    model: str | None
    vectors: list[list[float]] | None
    ai: AiMeta
    usage: LlmUsage | None = None

    @model_validator(mode="after")
    def _shape(self) -> "EmbedResponse":
        if self.ai.fallback:
            if self.vectors is not None:
                raise ValueError("대체 경로 응답에는 벡터를 담지 않는다")
            return self
        if self.vectors is None or self.model is None:
            raise ValueError("정상 응답에는 model과 vectors가 필요하다")
        if any(len(v) != EMBEDDING_DIM for v in self.vectors):
            raise ValueError(f"벡터 차원은 {EMBEDDING_DIM}이어야 한다")
        return self
