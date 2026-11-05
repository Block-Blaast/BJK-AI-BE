import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from bjk_server import ratelimit
from bjk_server.chat.interpreter import get_interpreter
from bjk_server.db.session import get_admin_db, get_db
from bjk_server.main import create_app
from bjk_server.security import create_access_token
from bjk_server.seed.demo import COMPANY_CODE, USERS, demo_id, seed_demo
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from .chat_fakes import NOW, FakeInterpreter

SERVER_DIR = Path(__file__).resolve().parents[1]
# 테스트 DB 정렬 로케일. compose·CI의 pgvector/pgvector:pg16 기본값과 같게 둔다.
TEST_DB_LOCALE = os.environ.get("TEST_DB_LOCALE", "en_US.UTF-8")
CHAT_URL = "/api/v1/chat/messages"


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


def ensure_app_login(admin_url: str) -> str:
    """bjk_app 역할 소속 로그인 계정을 만들고 그 계정의 접속 URL을 돌려준다."""
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
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
        database = make_url(admin_url).database
        conn.execute(text(f'GRANT CONNECT ON DATABASE "{database}" TO {APP_LOGIN}'))
    engine.dispose()
    url = make_url(admin_url).set(username=APP_LOGIN, password=APP_LOGIN)
    return url.render_as_string(hide_password=False)


@pytest.fixture(scope="session")
def app_db_url(migrated_db_url: str) -> str:
    """RLS가 적용되는 앱 계정 접속 URL. 운영과 같이 bjk_app 역할 소속 로그인 계정을 쓴다."""
    return ensure_app_login(migrated_db_url)


DEMO_TODAY = date(2026, 11, 4)


@dataclass
class DemoDB:
    """시연 시드를 넣은 테스트 DB. admin은 소유자, app은 RLS 적용 앱 계정 엔진."""

    admin: Engine
    app: Engine

    def reseed(self) -> None:
        with Session(self.admin) as s, s.begin():
            seed_demo(s, today=DEMO_TODAY)


@pytest.fixture(scope="module")
def demo_db() -> Iterator[DemoDB]:
    with temp_database(_base_url()) as url:
        command.upgrade(alembic_config(url), "head")
        db = DemoDB(admin=create_engine(url), app=create_engine(ensure_app_login(url)))
        db.reseed()
        yield db
        db.admin.dispose()
        db.app.dispose()


def build_client(db: DemoDB) -> TestClient:
    """앱 계정·소유자 계정 세션을 테스트 DB로 바꾼 클라이언트."""
    app = create_app()
    app_sessions = sessionmaker(db.app, expire_on_commit=False)
    admin_sessions = sessionmaker(db.admin, expire_on_commit=False)

    def app_db():
        with app_sessions.begin() as session:
            yield session

    def admin_db():
        with admin_sessions.begin() as session:
            yield session

    app.dependency_overrides[get_db] = app_db
    app.dependency_overrides[get_admin_db] = admin_db
    return TestClient(app)


@pytest.fixture
def client(demo_db: DemoDB) -> TestClient:
    return build_client(demo_db)


def auth_header(user_key: str) -> dict[str, str]:
    """시드 계정(owner, manager, worker, worker2)의 액세스 토큰 헤더."""
    user = next(u for u in USERS if u.key == user_key)
    token = create_access_token(
        demo_id("user", user.key), demo_id("company", COMPANY_CODE), user.role
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def chat(client, demo_db, monkeypatch):
    """가짜 해석기로 채팅 메시지를 보내는 함수. 시드와 호출 제한 시각을 고정한다."""
    demo_db.reseed()
    monkeypatch.setattr(ratelimit, "utcnow", lambda: NOW)
    client.app.dependency_overrides[get_interpreter] = FakeInterpreter
    counter = iter(range(10_000))

    def send(text, user="worker", client_message_id=None):
        body = {"client_message_id": client_message_id or f"m-{next(counter)}", "text": text}
        return client.post(CHAT_URL, json=body, headers=auth_header(user))

    return send
