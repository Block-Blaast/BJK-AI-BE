from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

Provider = Literal["bedrock", "gemini"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # 주 경로는 Bedrock. AWS 기본 자격 증명 체인(EC2 IAM Role 등)으로 인증해 API 키가 없다.
    llm_provider: Provider = "bedrock"
    # 임베딩은 폴백하지 않는다(다른 모델 벡터끼리 비교 불가). server DB 벡터와 같은 모델이어야 한다.
    embedding_provider: Provider = "bedrock"

    aws_region: str = "ap-northeast-3"
    # Haiku 4.5는 모든 Bedrock 고객에게 열려 있다. Haiku 5.5는 콘솔에서 접근 승인 후 바꾼다.
    bedrock_chat_model: str = "anthropic.claude-haiku-4-5"
    bedrock_opinion_model: str = "anthropic.claude-haiku-4-5"
    bedrock_import_model: str = "anthropic.claude-haiku-4-5"
    bedrock_embedding_model: str = "amazon.titan-embed-text-v2:0"
    # Haiku 4.5는 effort를 받지 않아 비워 둔다. Haiku 5.5 이상으로 바꾸면 지연을 줄이려 "low".
    bedrock_effort: str | None = None

    # Gemini는 키가 있을 때만 쓴다. llm_provider가 bedrock이면 LLM 재시도 폴백이 된다.
    gemini_api_key: str | None = None
    gemini_chat_model: str = "gemini-3.5-flash-lite"
    gemini_embedding_model: str = "gemini-embedding-2"
    gemini_opinion_model: str = "gemini-3.5-flash-lite"
    gemini_import_model: str = "gemini-3.5-flash-lite"

    # 채팅은 전송부터 확인 카드까지 3초(기능명세서 17장). server의 매칭·카드 몫을 남기고
    # 재시도까지 이 예산 안에서 끝낸다.
    chat_budget_seconds: float = 2.5
    embed_budget_seconds: float = 10.0
    # 검토는 요청부터 의견서까지 10초. server가 검증 실패로 최대 2번 더 부를 수 있어 한 번에 3초.
    opinion_budget_seconds: float = 3.0
    # 엑셀 이관은 실시간 응답이 아니라 넉넉히 준다(50줄 묶음 하나당).
    import_budget_seconds: float = 30.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
