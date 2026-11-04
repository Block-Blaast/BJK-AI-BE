from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # 앱이 쓰는 접속 정보.
    database_url: str = "postgresql+psycopg://bjk:bjk@localhost:5433/bjk"
    # 마이그레이션·시드용 소유자 계정. 비우면 database_url을 쓴다.
    admin_database_url: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
