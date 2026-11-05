"""merge candidates

Revision ID: 0027
Revises: 0026
Create Date: 2026-11-05 23:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0027"
down_revision: str | Sequence[str] | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "merge_candidates",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("company_id", sa.UUID(), nullable=False),
        sa.Column("part_a_id", sa.UUID(), nullable=False),
        sa.Column("part_b_id", sa.UUID(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("reason", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="open", nullable=False),
        sa.Column("representative_part_id", sa.UUID(), nullable=True),
        sa.Column("decided_by", sa.UUID(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("part_a_id < part_b_id", name=op.f("ck_merge_candidates_pair_order")),
        sa.CheckConstraint(
            "status IN ('open', 'count_requested', 'merged', 'different', 'closed')",
            name=op.f("ck_merge_candidates_status"),
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name=op.f("fk_merge_candidates_company_id_companies"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["part_a_id"],
            ["parts.id"],
            name=op.f("fk_merge_candidates_part_a_id_parts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["part_b_id"],
            ["parts.id"],
            name=op.f("fk_merge_candidates_part_b_id_parts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["representative_part_id"],
            ["parts.id"],
            name=op.f("fk_merge_candidates_representative_part_id_parts"),
        ),
        sa.ForeignKeyConstraint(
            ["decided_by"], ["users.id"], name=op.f("fk_merge_candidates_decided_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_merge_candidates")),
        sa.UniqueConstraint(
            "company_id",
            "part_a_id",
            "part_b_id",
            name=op.f("uq_merge_candidates_company_id"),
        ),
    )
    op.create_index(
        op.f("ix_merge_candidates_company_id"), "merge_candidates", ["company_id"], unique=False
    )
    op.execute("ALTER TABLE merge_candidates ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON merge_candidates TO bjk_app "
        "USING (company_id = app_company_id()) WITH CHECK (company_id = app_company_id())"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP POLICY tenant_isolation ON merge_candidates")
    op.drop_index(op.f("ix_merge_candidates_company_id"), table_name="merge_candidates")
    op.drop_table("merge_candidates")
