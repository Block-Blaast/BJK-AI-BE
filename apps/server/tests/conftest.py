import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

SERVER_DIR = Path(__file__).resolve().parents[1]
# 테스트 DB 정렬 로케일. compose·CI의 postgres:16 기본값과 같게 둔다.
TEST_DB_LOCALE = os.environ.get("TEST_DB_LOCALE", "en_US.UTF-8")


def _base_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        # CI는 REQUIRE_DB_TESTS=1로 DB 테스트를 건너뛰지 못하게 한다.
        if os.environ.get("REQUIRE_DB_TESTS") == "1":
            pytest.fail("REQUIRE_DB_TESTS=1인데 TEST_DATABASE_URL이 없습니다.")
        pytest.skip("TEST_DATABASE_URL 미설정: DB 테스트 생략")
    return url


@contextmanager
def temp_database(base_url: str) -> Iterator[str]:
    """테스트마다 독립된 빈 DB를 만들고 끝나면 지운다."""
    base = make_url(base_url)
    name = f"bjk_test_{uuid.uuid4().hex[:12]}"
    engine = create_engine(base, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        # 서버 기본 로케일(로컬 C, CI·운영 en_US)과 관계없이 운영과 같은 정렬 규칙으로 만든다.
        conn.execute(
            text(
                f"CREATE DATABASE \"{name}\" TEMPLATE template0 ENCODING 'UTF8' "
                f"LC_COLLATE '{TEST_DB_LOCALE}' LC_CTYPE '{TEST_DB_LOCALE}'"
            )
        )
    try:
        yield base.set(database=name).render_as_string(hide_password=False)
    finally:
        with engine.connect() as conn:
            conn.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        engine.dispose()


def alembic_config(url: str) -> Config:
    config = Config(str(SERVER_DIR / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


@pytest.fixture
def empty_db_url() -> Iterator[str]:
    with temp_database(_base_url()) as url:
        yield url


@pytest.fixture(scope="session")
def migrated_db_url() -> Iterator[str]:
    with temp_database(_base_url()) as url:
        command.upgrade(alembic_config(url), "head")
        yield url


APP_LOGIN = "bjk_app_test"


@pytest.fixture(scope="session")
def app_db_url(migrated_db_url: str) -> str:
    """RLS가 적용되는 앱 계정 접속 URL. 운영과 같이 bjk_app 역할 소속 로그인 계정을 쓴다."""
    engine = create_engine(migrated_db_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        conn.execute(
            text(
                f"""
                DO $$ BEGIN
                    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{APP_LOGIN}') THEN
                        CREATE ROLE {APP_LOGIN} LOGIN PASSWORD '{APP_LOGIN}' IN ROLE bjk_app;
                    END IF;
                END $$
                """
            )
        )
        database = make_url(migrated_db_url).database
        conn.execute(text(f'GRANT CONNECT ON DATABASE "{database}" TO {APP_LOGIN}'))
    engine.dispose()
    url = make_url(migrated_db_url).set(username=APP_LOGIN, password=APP_LOGIN)
    return url.render_as_string(hide_password=False)
