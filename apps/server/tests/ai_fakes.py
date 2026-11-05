"""가짜 ai 서비스. 응답 본문은 실제 계약 모델(bjk_contracts)로 만들어 계약 그대로 주고받는다."""

import json
import math
import zlib

import httpx
from bjk_contracts import (
    EMBEDDING_DIM,
    AiMeta,
    ChatIntent,
    ChatParseResponse,
    EmbedResponse,
    FallbackReason,
    LlmPurpose,
    LlmUsage,
    OpinionRequest,
    OpinionResponse,
    ParsedItem,
)
from bjk_review import template_opinion
from bjk_server.ai.client import AiClient

EMBED_MODEL = "amazon.titan-embed-text-v2:0"


def usage(purpose: LlmPurpose, success: bool = True) -> LlmUsage:
    return LlmUsage(
        purpose=purpose,
        model="test-model",
        input_tokens=40,
        output_tokens=8,
        latency_ms=120,
        attempts=1 if success else 2,
        success=success,
    )


def vector(weights: dict[int, float]) -> list[float]:
    """축 번호 → 값으로 만든 L2 정규화 벡터."""
    values = [0.0] * EMBEDDING_DIM
    for axis, weight in weights.items():
        values[axis] = weight
    norm = math.sqrt(sum(v * v for v in values))
    return [v / norm for v in values]


def text_vector(text: str) -> list[float]:
    """등록하지 않은 문장은 문장마다 다른 축(200번 이후)에 둔다. 서로 거의 직교한다."""
    return vector({200 + zlib.crc32(text.encode()) % (EMBEDDING_DIM - 200): 1.0})


def parsed(intent: str, **item) -> ChatParseResponse:
    return ChatParseResponse(
        intent=ChatIntent(intent),
        items=[ParsedItem(**item)] if item else [],
        ai=AiMeta.ok(),
        usage=usage(LlmPurpose.CHAT_PARSE),
    )


def parse_failed(reason: FallbackReason) -> ChatParseResponse:
    return ChatParseResponse(
        intent=None, ai=AiMeta.failed(reason), usage=usage(LlmPurpose.CHAT_PARSE, False)
    )


class FakeAi:
    """경로별 계약 응답을 돌려준다. `requests`에 받은 (경로, 본문)을 남긴다.

    `fail`이 예외면 그 예외(연결 실패·시간 초과)를, 숫자면 그 HTTP 상태를 돌려준다.
    """

    def __init__(
        self,
        chat: dict[str, ChatParseResponse] | None = None,
        vectors: dict[str, list[float]] | None = None,
        fail: Exception | int | None = None,
    ) -> None:
        self.chat = chat or {}
        self.vectors = vectors or {}
        self.fail = fail
        self.embed_fallback = False
        # 의견서: 기본은 검증을 통과하는 양식 문장. 함수를 넣으면 그 문장(None이면 대체 응답)
        self.opinion_text = None
        self.llm = "ok"
        self.requests: list[tuple[str, dict | None]] = []

    def paths(self) -> list[str]:
        return [path for path, _ in self.requests]

    def client(self) -> AiClient:
        transport = httpx.MockTransport(self._handle)
        return AiClient(httpx.Client(base_url="http://ai", transport=transport))

    def _handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        self.requests.append((request.url.path, body))
        if isinstance(self.fail, Exception):
            raise self.fail
        if isinstance(self.fail, int):
            return httpx.Response(self.fail, json={"detail": "fail"})
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok", "llm": self.llm})
        if request.url.path == "/v1/chat/parse":
            return _json(self.chat[body["text"]])
        if request.url.path == "/v1/embeddings":
            return _json(self._embed(body["texts"]))
        if request.url.path == "/v1/opinions":
            return _json(self._opinion(OpinionRequest.model_validate(body)))
        return httpx.Response(404)

    def _embed(self, texts: list[str]) -> EmbedResponse:
        if self.embed_fallback:
            return EmbedResponse(
                model=None, vectors=None, ai=AiMeta.failed(FallbackReason.TIMEOUT), usage=None
            )
        return EmbedResponse(
            model=EMBED_MODEL,
            vectors=[self.vectors.get(t) or text_vector(t) for t in texts],
            ai=AiMeta.ok(),
            usage=usage(LlmPurpose.EMBEDDING),
        )

    def _opinion(self, request: OpinionRequest) -> OpinionResponse:
        text = self.opinion_text(request) if self.opinion_text else template_opinion(request)
        if text is None:
            return OpinionResponse(
                text=None,
                ai=AiMeta.failed(FallbackReason.TIMEOUT),
                usage=usage(LlmPurpose.OPINION, False),
            )
        return OpinionResponse(text=text, ai=AiMeta.ok(), usage=usage(LlmPurpose.OPINION))


def _json(model) -> httpx.Response:
    return httpx.Response(200, json=model.model_dump(mode="json"))
