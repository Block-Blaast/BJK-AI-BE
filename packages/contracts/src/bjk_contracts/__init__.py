"""server ↔ ai 내부 API 계약(요청·응답 스키마)을 둔다."""

from bjk_contracts.chat import (
    CHAT_TEXT_MAX_LEN,
    ChatIntent,
    ChatParseRequest,
    ChatParseResponse,
    ParsedItem,
)
from bjk_contracts.common import AiMeta, FallbackReason, LlmPurpose, LlmUsage
from bjk_contracts.embedding import (
    EMBED_MAX_TEXTS,
    EMBED_TEXT_MAX_LEN,
    EMBEDDING_DIM,
    EmbedRequest,
    EmbedResponse,
    EmbedTask,
)

__all__ = [
    "CHAT_TEXT_MAX_LEN",
    "EMBED_MAX_TEXTS",
    "EMBED_TEXT_MAX_LEN",
    "EMBEDDING_DIM",
    "AiMeta",
    "ChatIntent",
    "ChatParseRequest",
    "ChatParseResponse",
    "EmbedRequest",
    "EmbedResponse",
    "EmbedTask",
    "FallbackReason",
    "LlmPurpose",
    "LlmUsage",
    "ParsedItem",
]
