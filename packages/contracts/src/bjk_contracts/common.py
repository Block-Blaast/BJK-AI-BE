"""server ↔ ai 응답에 공통으로 붙는 AI 메타와 토큰 사용량."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FallbackReason(StrEnum):
    """대체 경로로 간 이유 (API 명세서 1-6)."""

    TIMEOUT = "timeout"
    ERROR = "error"
    SCHEMA_INVALID = "schema_invalid"
    QUOTA_EXCEEDED = "quota_exceeded"
    VERIFY_FAILED = "verify_failed"


class AiMeta(BaseModel):
    """API 응답의 `ai` 객체와 같은 모양. server가 그대로 클라이언트에 붙인다."""

    model_config = ConfigDict(frozen=True)

    used: bool
    fallback: bool
    reason: FallbackReason | None = None

    @model_validator(mode="after")
    def _reason_only_on_fallback(self) -> "AiMeta":
        if self.fallback != (self.reason is not None):
            raise ValueError("fallback이면 reason이 필요하고, 아니면 reason은 비어 있어야 한다")
        return self

    @classmethod
    def ok(cls) -> "AiMeta":
        return cls(used=True, fallback=False)

    @classmethod
    def failed(cls, reason: FallbackReason) -> "AiMeta":
        return cls(used=True, fallback=True, reason=reason)


class LlmPurpose(StrEnum):
    """`llm_calls.용도`. 호출 지점마다 하나."""

    CHAT_PARSE = "chat_parse"
    IMPORT_SUGGEST = "import_suggest"
    OPINION = "opinion"
    EMBEDDING = "embedding"


class LlmUsage(BaseModel):
    """호출 한 번의 비용·장애 기록. server가 `llm_calls`에 저장한다.

    재시도까지 합친 값이다. 토큰은 제공자가 돌려준 값이 없으면 0.
    """

    model_config = ConfigDict(frozen=True)

    purpose: LlmPurpose
    model: str
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    latency_ms: int = Field(ge=0)
    attempts: int = Field(ge=1)
    success: bool
