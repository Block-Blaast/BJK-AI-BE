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


def _base_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL 미설정: DB 테스트 생략")
    return url


@contextmanager
def temp_database(base_url: str) -> Iterator[str]:
    """테스트마다 독립된 빈 DB를 만들고 끝나면 지운다."""
    base = make_url(base_url)
    name = f"bjk_test_{uuid.uuid4().hex[:12]}"
    engine = create_engine(base, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
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
