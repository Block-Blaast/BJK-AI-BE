"""system company ids

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-05

배치는 RLS가 적용되는 앱 계정으로 돈다. 회사를 하나씩 지정하려면 회사 ID 목록이 먼저 필요하므로,
소유자 권한으로 실행되는 함수가 ID만 돌려준다. 회사 이름·코드 등 다른 값은 주지 않는다.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0010"
down_revision: str | Sequence[str] | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION system_company_ids() RETURNS SETOF uuid
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = public, pg_temp AS
        $$ SELECT id FROM companies ORDER BY created_at, id $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION system_company_ids() FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION system_company_ids() TO bjk_app")


def downgrade() -> None:
    op.execute("DROP FUNCTION system_company_ids()")
