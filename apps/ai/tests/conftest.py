import asyncio

import pytest
from bjk_ai.config import Settings
from bjk_ai.gateway import EmbedResult, GenerateResult
from bjk_ai.main import create_app
from fastapi.testclient import TestClient

COMPANY_ID = "6f1c2f9e-6d1a-4c3e-9a51-2b7f0c8d4e11"


class FakeGateway:
    """응답을 순서대로 돌려준다. 예외 객체면 던지고, 실수면 그만큼 기다린다."""

    def __init__(self, *, texts=(), vectors=()):
        self.texts = list(texts)
        self.vectors = list(vectors)
        self.generate_calls = []
        self.embed_calls = []

    async def generate_json(self, *, model, system, prompt, schema):
        self.generate_calls.append(prompt)
        return GenerateResult(text=await self._next(self.texts), input_tokens=10, output_tokens=5)

    async def embed(self, *, model, texts, dim):
        self.embed_calls.append((texts, dim))
        return EmbedResult(vectors=await self._next(self.vectors), input_tokens=0)

    @staticmethod
    async def _next(queue):
        value = queue.pop(0)
        if isinstance(value, BaseException):
            raise value
        if isinstance(value, float):
            await asyncio.sleep(value)
        return value


@pytest.fixture
def company_id():
    return COMPANY_ID


@pytest.fixture
def fake_gateway():
    """`fake_gateway(texts=[...])`로 가짜 게이트웨이를 만든다."""
    return FakeGateway


@pytest.fixture
def make_client():
    """`make_client(gateway, **settings)`. gateway가 None이면 API 키 미설정 상태다."""

    def _make(gateway=None, **overrides):
        settings = Settings(_env_file=None, gemini_api_key=None, **overrides)
        return TestClient(create_app(settings=settings, gateway=gateway))

    return _make
