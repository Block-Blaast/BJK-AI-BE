"""auth lookup functions

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-05

로그인 시점에는 회사가 정해지지 않아 RLS로 사용자를 찾을 수 없다. 소유자 권한으로 실행되는
조회 함수가 이메일에 해당하는 사용자·회사 ID만 돌려주고, 이후 조회는 그 회사로 RLS 안에서 한다.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION auth_lookup_by_email(p_email text)
        RETURNS TABLE (user_id uuid, company_id uuid)
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = public, pg_temp AS
        $$ SELECT id, company_id FROM users WHERE lower(email) = lower(p_email) AND active $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION auth_lookup_by_email(text) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION auth_lookup_by_email(text) TO bjk_app")


def downgrade() -> None:
    op.execute("DROP FUNCTION auth_lookup_by_email(text)")
