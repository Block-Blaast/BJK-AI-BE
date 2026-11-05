"""twin layouts

Revision ID: 0031
Revises: 0030
Create Date: 2026-11-05 23:50:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0031"
down_revision: str | Sequence[str] | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "twin_layouts",
        sa.Column("company_id", sa.UUID(), nullable=False),
        sa.Column("layout", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name=op.f("fk_twin_layouts_company_id_companies"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("company_id", name=op.f("pk_twin_layouts")),
    )

    op.execute("ALTER TABLE twin_layouts ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON twin_layouts TO bjk_app "
        "USING (company_id = app_company_id()) WITH CHECK (company_id = app_company_id())"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP POLICY tenant_isolation ON twin_layouts")
    op.drop_table("twin_layouts")
