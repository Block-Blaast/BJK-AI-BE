"""events

Revision ID: 0022
Revises: 0021
Create Date: 2026-11-05

SSE 실시간 이벤트 (API 명세서 NOT-03). 연결이 끊겨도 Last-Event-ID로 이어 받도록 저장한다.
id는 SSE 이벤트 ID로 그대로 쓰는 증가 정수다.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0022"
down_revision: str | Sequence[str] | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "events",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("company_id", sa.UUID(), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name=op.f("fk_events_company_id_companies"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_events")),
    )
    op.create_index("ix_events_company_id_id", "events", ["company_id", "id"], unique=False)
    op.execute("ALTER TABLE events ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON events TO bjk_app "
        "USING (company_id = app_company_id()) WITH CHECK (company_id = app_company_id())"
    )


def downgrade() -> None:
    op.execute("DROP POLICY tenant_isolation ON events")
    op.drop_index("ix_events_company_id_id", table_name="events")
    op.drop_table("events")
