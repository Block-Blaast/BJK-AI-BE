import uuid

import pytest
from bjk_server.auth import set_tenant
from bjk_server.db.models import Company, Movement, Part
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import DBAPIError, ProgrammingError
from sqlalchemy.orm import Session


@pytest.fixture(scope="module")
def two_companies(migrated_db_url):
    """소유자 계정으로 회사 두 곳과 부품을 만든다."""
    engine = create_engine(migrated_db_url)
    with Session(engine) as s, s.begin():
        a = Company(name="A", code=uuid.uuid4().hex[:8])
        b = Company(name="B", code=uuid.uuid4().hex[:8])
        s.add_all([a, b])
        s.flush()
        s.add_all(
            [
                Part(company_id=a.id, name="A부품", unit="개"),
                Part(company_id=b.id, name="B부품1", unit="개"),
                Part(company_id=b.id, name="B부품2", unit="개"),
            ]
        )
        ids = (a.id, b.id)
    engine.dispose()
    return ids


@pytest.fixture
def app_session(app_db_url):
    engine = create_engine(app_db_url)
    with Session(engine) as s:
        yield s
        s.rollback()
    engine.dispose()


def test_app_role_cannot_bypass_rls(app_session):
    row = app_session.execute(
        text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
    ).one()
    assert row == (False, False)


def test_without_company_nothing_is_visible(app_session, two_companies):
    assert app_session.scalar(select(func.count()).select_from(Part)) == 0
    assert app_session.scalar(select(func.count()).select_from(Company)) == 0


def test_company_sees_only_own_rows(app_session, two_companies):
    a, b = two_companies
    set_tenant(app_session, b)
    names = app_session.scalars(select(Part.name).order_by(Part.name)).all()
    assert names == ["B부품1", "B부품2"]
    assert app_session.scalars(select(Company.id)).all() == [b]

    other = select(func.count()).select_from(Part).where(Part.company_id == a)
    assert app_session.scalar(other) == 0


def test_cannot_write_into_other_company(app_session, two_companies):
    a, b = two_companies
    set_tenant(app_session, a)
    app_session.add(Part(company_id=b, name="침투", unit="개"))
    with pytest.raises(ProgrammingError, match="row-level security"):
        app_session.flush()


def test_tenant_setting_is_local_to_transaction(app_db_url, two_companies):
    engine = create_engine(app_db_url)
    with engine.connect() as conn:
        with conn.begin():
            set_tenant(Session(bind=conn), two_companies[0])
            assert conn.scalar(select(func.count()).select_from(Part)) == 1
        with conn.begin():
            assert conn.scalar(select(func.count()).select_from(Part)) == 0
    engine.dispose()


def test_app_role_cannot_update_movements(app_session, two_companies):
    a, _ = two_companies
    set_tenant(app_session, a)
    part = app_session.scalar(select(Part.id))
    app_session.add(Movement(company_id=a, part_id=part, type="IN", qty=1))
    app_session.flush()
    with pytest.raises(DBAPIError, match="permission denied"):
        app_session.execute(text("UPDATE movements SET qty = 2"))


def test_tenant_db_dependency_scopes_request_to_token_company(app_db_url, two_companies):
    from bjk_server.auth import TenantDB
    from bjk_server.db.session import get_db
    from bjk_server.main import create_app
    from bjk_server.security import create_access_token
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(app_db_url)
    factory = sessionmaker(engine)

    def override_db():
        with factory.begin() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db] = override_db

    @app.get("/_test/parts")
    def parts(db: TenantDB):
        return db.scalars(select(Part.name).order_by(Part.name)).all()

    client = TestClient(app)
    for company, expected in zip(two_companies, [["A부품"], ["B부품1", "B부품2"]], strict=True):
        token = create_access_token(uuid.uuid4(), company, "worker")
        res = client.get("/_test/parts", headers={"Authorization": f"Bearer {token}"})
        assert res.json() == expected
    engine.dispose()
