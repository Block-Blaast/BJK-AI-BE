from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from bjk_server.config import get_settings


@lru_cache
def get_engine() -> Engine:
    return create_engine(get_settings().database_url, pool_pre_ping=True)


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(get_engine(), expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """요청 하나에 트랜잭션 하나. 정상 종료 시 커밋, 예외 시 롤백."""
    with get_sessionmaker().begin() as session:
        yield session


@lru_cache
def get_admin_engine() -> Engine:
    """소유자 계정 엔진. 시드 초기화처럼 RLS 밖에서 해야 하는 개발 전용 작업에만 쓴다."""
    settings = get_settings()
    return create_engine(settings.admin_database_url or settings.database_url, pool_pre_ping=True)


def get_admin_db() -> Iterator[Session]:
    with sessionmaker(get_admin_engine(), expire_on_commit=False).begin() as session:
        yield session
