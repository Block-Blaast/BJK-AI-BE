import asyncio
import io
import json
from types import SimpleNamespace

import pytest
from bjk_ai.config import Settings
from bjk_ai.gateway import (
    BedrockGateway,
    GeminiGateway,
    ProviderUnavailable,
    RoutedGateway,
    _PerLoopClient,
    build_gateway,
)
from bjk_contracts import EmbedTask, LlmPurpose
from pydantic import BaseModel

MODELS = {
    LlmPurpose.CHAT_PARSE: "anthropic.claude-haiku-4-5",
    LlmPurpose.OPINION: "anthropic.claude-haiku-4-5",
    LlmPurpose.IMPORT_SUGGEST: "anthropic.claude-haiku-4-5",
}


class Output(BaseModel):
    intent: str


class FakeMessages:
    def __init__(self, stop_reason="end_turn"):
        self.calls = []
        self.stop_reason = stop_reason

    async def parse(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            stop_reason=self.stop_reason,
            content=[SimpleNamespace(type="text", text='{"intent": "OUT"}')],
            usage=SimpleNamespace(input_tokens=12, output_tokens=7),
        )


class FakeRuntime:
    def __init__(self):
        self.calls = []

    def invoke_model(self, **kwargs):
        self.calls.append(kwargs)
        body = json.loads(kwargs["body"])
        vector = [0.5] * body["dimensions"]
        payload = {"embedding": vector, "inputTextTokenCount": len(body["inputText"])}
        return {"body": io.BytesIO(json.dumps(payload).encode())}


def bedrock(messages=None, runtime=None, effort=None):
    messages = messages or FakeMessages()
    return BedrockGateway(
        region="ap-northeast-3",
        models=MODELS,
        embedding_model="amazon.titan-embed-text-v2:0",
        effort=effort,
        claude_factory=lambda: SimpleNamespace(messages=messages),
        runtime_client=runtime or FakeRuntime(),
    )


def generate(gateway, attempt=1):
    return asyncio.run(
        gateway.generate_json(
            purpose=LlmPurpose.CHAT_PARSE,
            system="sys",
            prompt="3호기 베어링 두 개 씀",
            schema=Output,
            max_tokens=1024,
            attempt=attempt,
        )
    )


def test_bedrock_generate_uses_structured_output():
    messages = FakeMessages()
    result = generate(bedrock(messages))

    [call] = messages.calls
    assert call["model"] == "anthropic.claude-haiku-4-5"
    assert call["output_format"] is Output
    assert call["system"] == "sys"
    assert call["messages"] == [{"role": "user", "content": "3호기 베어링 두 개 씀"}]
    assert "output_config" not in call
    assert (result.text, result.input_tokens, result.output_tokens) == ('{"intent": "OUT"}', 12, 7)
    assert result.model == "anthropic.claude-haiku-4-5"


def test_bedrock_effort_is_sent_only_when_set():
    messages = FakeMessages()
    generate(bedrock(messages, effort="low"))

    assert messages.calls[0]["output_config"] == {"effort": "low"}


@pytest.mark.parametrize("stop_reason", ["refusal", "max_tokens"])
def test_bedrock_unusable_stop_reason_raises(stop_reason):
    with pytest.raises(RuntimeError):
        generate(bedrock(FakeMessages(stop_reason=stop_reason)))


def test_bedrock_embed_calls_titan_per_text():
    runtime = FakeRuntime()
    gateway = bedrock(runtime=runtime)
    result = asyncio.run(gateway.embed(texts=[" 볼트 ", "너트"], dim=1024, task=EmbedTask.QUERY))

    bodies = [json.loads(c["body"]) for c in runtime.calls]
    assert sorted(b["inputText"] for b in bodies) == ["너트", "볼트"]
    assert all(b == {**b, "dimensions": 1024, "normalize": True} for b in bodies)
    assert all(c["modelId"] == "amazon.titan-embed-text-v2:0" for c in runtime.calls)
    assert [len(v) for v in result.vectors] == [1024, 1024]
    assert result.input_tokens == 4
    assert result.model == "amazon.titan-embed-text-v2:0"


def test_client_is_recreated_per_event_loop():
    holder = _PerLoopClient(object)

    async def twice():
        return holder.get(), holder.get()

    first, same = asyncio.run(twice())
    second, _ = asyncio.run(twice())

    assert first is same
    assert first is not second


class Recorder:
    def __init__(self, name):
        self.name = name

    async def generate_json(self, **kwargs):
        return self.name

    async def embed(self, **kwargs):
        return self.name


def route(gateway, attempt):
    return asyncio.run(gateway.generate_json(attempt=attempt, purpose=LlmPurpose.OPINION))


def test_routed_gateway_retries_on_fallback_and_never_mixes_embeddings():
    gateway = RoutedGateway(
        llm=Recorder("bedrock"), llm_fallback=Recorder("gemini"), embedder=Recorder("bedrock")
    )

    assert route(gateway, 1) == "bedrock"
    assert route(gateway, 2) == "gemini"
    assert asyncio.run(gateway.embed(texts=["a"], dim=1024, task=EmbedTask.QUERY)) == "bedrock"


def test_routed_gateway_without_fallback_retries_primary():
    gateway = RoutedGateway(llm=Recorder("bedrock"), embedder=None)

    assert route(gateway, 2) == "bedrock"
    with pytest.raises(ProviderUnavailable):
        asyncio.run(gateway.embed(texts=["a"], dim=1024, task=EmbedTask.QUERY))


def settings(**overrides):
    return Settings(_env_file=None, **{"gemini_api_key": None, **overrides})


def test_build_gateway_prefers_bedrock_with_gemini_fallback():
    gateway = build_gateway(settings(gemini_api_key="k"), aws_available=lambda region: True)

    assert isinstance(gateway.llm, BedrockGateway)
    assert isinstance(gateway.llm_fallback, GeminiGateway)
    assert isinstance(gateway.embedder, BedrockGateway)


def test_build_gateway_bedrock_only():
    gateway = build_gateway(settings(), aws_available=lambda region: True)

    assert isinstance(gateway.llm, BedrockGateway)
    assert gateway.llm_fallback is None


def test_build_gateway_without_aws_uses_gemini_llm_but_no_embedding():
    gateway = build_gateway(settings(gemini_api_key="k"), aws_available=lambda region: False)

    assert isinstance(gateway.llm, GeminiGateway)
    assert gateway.llm_fallback is None
    # 임베딩은 server DB 벡터와 같은 모델이어야 해서 다른 제공자로 대신하지 않는다
    assert gateway.embedder is None


def test_build_gateway_nothing_configured():
    assert build_gateway(settings(), aws_available=lambda region: False) is None


def test_build_gateway_checks_configured_region():
    seen = []
    build_gateway(settings(aws_region="ap-northeast-1"), aws_available=seen.append)

    assert seen == ["ap-northeast-1"]
