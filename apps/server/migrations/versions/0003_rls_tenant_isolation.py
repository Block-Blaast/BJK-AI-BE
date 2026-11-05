"""rls tenant isolation

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-05

앱 계정은 bjk_app 역할에 속한 로그인 계정으로 접속한다. bjk_app은 테이블 소유자도
superuser도 아니므로 RLS를 우회하지 못한다. 회사는 요청 트랜잭션마다
set_config('app.company_id', ..., true)로 지정한다.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "bjk_app"

# company_id 열로 회사를 구분하는 테이블
TENANT_TABLES = [
    "users",
    "company_settings",
    "categories",
    "parts",
    "part_aliases",
    "suppliers",
    "supplier_parts",
    "equipment",
    "equipment_parts",
    "maintenance",
    "movements",
    "idempotency_keys",
]


def upgrade() -> None:
    op.execute(
        f"""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                CREATE ROLE {APP_ROLE} NOLOGIN;
            END IF;
        END $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app_company_id() RETURNS uuid
        LANGUAGE sql STABLE AS
        $$ SELECT NULLIF(current_setting('app.company_id', true), '')::uuid $$
        """
    )

    op.execute(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {APP_ROLE}")
    # 이후 마이그레이션이 만드는 테이블에도 같은 권한을 준다.
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {APP_ROLE}"
    )
    # 원장은 추가 전용. 트리거와 별도로 권한에서도 막는다.
    op.execute(f"REVOKE UPDATE, DELETE ON movements FROM {APP_ROLE}")
    op.execute(f"REVOKE ALL ON alembic_version FROM {APP_ROLE}")

    op.execute("ALTER TABLE companies ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON companies TO {APP_ROLE} "
        "USING (id = app_company_id()) WITH CHECK (id = app_company_id())"
    )
    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} TO {APP_ROLE} "
            "USING (company_id = app_company_id()) WITH CHECK (company_id = app_company_id())"
        )


def downgrade() -> None:
    for table in ["companies", *TENANT_TABLES]:
        op.execute(f"DROP POLICY tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM {APP_ROLE}"
    )
    op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {APP_ROLE}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {APP_ROLE}")
    op.execute("DROP FUNCTION app_company_id()")
    # 역할은 클러스터 전체에서 공유하므로 지우지 않는다.
