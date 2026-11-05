from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # LLM과 임베딩 모두 이 키 하나로 호출한다. 비어 있으면 호출하지 않고 대체 응답을 준다.
    gemini_api_key: str | None = None
    gemini_chat_model: str = "gemini-3.5-flash-lite"
    gemini_embedding_model: str = "gemini-embedding-2"

    # 채팅은 전송부터 확인 카드까지 3초(기능명세서 17장). server의 매칭·카드 몫을 남기고
    # 재시도까지 이 예산 안에서 끝낸다.
    chat_budget_seconds: float = 2.5
    embed_budget_seconds: float = 10.0

    @property
    def llm_configured(self) -> bool:
        return bool(self.gemini_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
