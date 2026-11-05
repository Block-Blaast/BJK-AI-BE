"""notifications

Revision ID: 0021
Revises: 0020
Create Date: 2026-11-05 22:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0021"
down_revision: str | Sequence[str] | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "notifications",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("company_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("target_type", sa.String(length=16), nullable=True),
        sa.Column("target_id", sa.UUID(), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("channels", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("dedupe_key", sa.String(length=200), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('review_completed', 'review_urgent', 'briefing', 'decision_result', "
            "'order_check', 'receipt_check', 'count_request', 'maintenance_check')",
            name=op.f("ck_notifications_kind"),
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name=op.f("fk_notifications_company_id_companies"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_notifications_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications")),
        sa.UniqueConstraint("user_id", "dedupe_key", name="uq_notifications_user_dedupe"),
    )
    op.create_index(
        op.f("ix_notifications_company_id"), "notifications", ["company_id"], unique=False
    )
    op.create_index(
        "ix_notifications_user_sent", "notifications", ["user_id", "sent_at"], unique=False
    )

    op.execute("ALTER TABLE notifications ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON notifications TO bjk_app "
        "USING (company_id = app_company_id()) WITH CHECK (company_id = app_company_id())"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP POLICY tenant_isolation ON notifications")
    op.drop_index("ix_notifications_user_sent", table_name="notifications")
    op.drop_index(op.f("ix_notifications_company_id"), table_name="notifications")
    op.drop_table("notifications")
