from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_JWT_SECRET = "dev-only-jwt-secret-change-me-in-production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # dev: 개발·시연 환경, 그 외 값은 운영으로 본다.
    app_env: str = "dev"
    # 앱이 쓰는 접속 정보. RLS가 적용되는 앱 계정(bjk_app 역할 소속)으로 연결한다.
    database_url: str = "postgresql+psycopg://bjk_app_login:bjk_app_login@localhost:5433/bjk"
    # 마이그레이션·시드용 소유자 계정. 비우면 database_url을 쓴다.
    admin_database_url: str | None = None

    # 배치 예약 스케줄러 동시 실행 작업 수. DB 연결 풀도 같은 크기로 잡는다.
    scheduler_workers: int = 2

    # ai 서비스 주소 (compose 안 http://ai:8001, 로컬 http://localhost:8001).
    # 비우면 ai를 부르지 않고 채팅은 폼 입력, 매칭은 규격·철자만으로 동작한다.
    ai_base_url: str | None = None

    jwt_secret: str = DEV_JWT_SECRET
    access_token_minutes: int = 15
    refresh_token_days: int = 14

    @property
    def is_dev(self) -> bool:
        return self.app_env == "dev"

    @model_validator(mode="after")
    def _require_secret_outside_dev(self) -> "Settings":
        if not self.is_dev and (self.jwt_secret == DEV_JWT_SECRET or len(self.jwt_secret) < 32):
            raise ValueError("운영 환경에서는 32자 이상의 JWT_SECRET을 설정해야 합니다.")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
