"""invites

Revision ID: 0021
Revises: 0020
Create Date: 2026-11-05

직원 초대 토큰 (API 명세서 AUTH-06·07). 토큰 원문은 저장하지 않고 SHA-256 해시만 둔다.
수락 시점에는 회사를 알 수 없어, 소유자 권한 조회 함수가 해시로 초대·회사 ID만 돌려준다.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: str | Sequence[str] | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "invites",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("company_id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("used_by", sa.UUID(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("role IN ('worker', 'manager')", name=op.f("ck_invites_role")),
        sa.CheckConstraint(
            "(used_at IS NULL) = (used_by IS NULL)", name=op.f("ck_invites_used_pair")
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name=op.f("fk_invites_company_id_companies"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_invites_created_by_users")
        ),
        sa.ForeignKeyConstraint(["used_by"], ["users.id"], name=op.f("fk_invites_used_by_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invites")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_invites_token_hash")),
    )
    op.create_index(op.f("ix_invites_company_id"), "invites", ["company_id"], unique=False)
    op.execute("ALTER TABLE invites ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON invites TO bjk_app "
        "USING (company_id = app_company_id()) WITH CHECK (company_id = app_company_id())"
    )
    op.execute(
        """
        CREATE FUNCTION auth_invite_by_token(p_token_hash text)
        RETURNS TABLE (invite_id uuid, company_id uuid)
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = public, pg_temp AS
        $$ SELECT id, company_id FROM invites WHERE token_hash = p_token_hash $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION auth_invite_by_token(text) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION auth_invite_by_token(text) TO bjk_app")


def downgrade() -> None:
    op.execute("DROP FUNCTION auth_invite_by_token(text)")
    op.execute("DROP POLICY tenant_isolation ON invites")
    op.drop_index(op.f("ix_invites_company_id"), table_name="invites")
    op.drop_table("invites")
