"""reviews

Revision ID: 0023
Revises: 0022
Create Date: 2026-11-05

발주 검토와 스냅샷 (API 명세서 REV-01·02, 2장 코드값 사전).
검토 하나에 스냅샷이 여러 개일 수 있다. 결정 직전 스냅샷이 오래돼 갱신하면 새 행을 추가하고
현재 스냅샷은 가장 최근 행이다. 스냅샷에는 그때 쓴 설정값을 함께 저장해 판정을 재현한다.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0023"
down_revision: str | Sequence[str] | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ["reviews", "review_snapshots"]


def _fk(table: str, column: str, target: str, **kwargs) -> sa.ForeignKeyConstraint:
    ref_table = target.split(".")[0]
    return sa.ForeignKeyConstraint(
        [column], [target], name=op.f(f"fk_{table}_{column}_{ref_table}"), **kwargs
    )


def upgrade() -> None:
    op.create_table(
        "reviews",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("company_id", sa.UUID(), nullable=False),
        sa.Column("entry", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="reviewing", nullable=False),
        sa.Column("verdict", sa.String(length=8), nullable=True),
        sa.Column("flags", postgresql.ARRAY(sa.Text()), server_default="{}", nullable=False),
        sa.Column("hold_reasons", postgresql.ARRAY(sa.Text()), server_default="{}", nullable=False),
        sa.Column("part_id", sa.UUID(), nullable=True),
        sa.Column("requested_by", sa.UUID(), nullable=True),
        sa.Column("source_message_id", sa.UUID(), nullable=True),
        sa.Column("request", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("opinion", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("original_total", sa.BigInteger(), nullable=True),
        sa.Column("saving", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("loss", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("decided_by", sa.UUID(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "entry IN ('staff_request', 'stock_draft', 'missed_draft')",
            name=op.f("ck_reviews_entry"),
        ),
        sa.CheckConstraint(
            "status IN ('reviewing', 'reviewed', 'held', 'approved', 'closed', 'expired')",
            name=op.f("ck_reviews_status"),
        ),
        sa.CheckConstraint(
            "verdict IS NULL OR verdict IN ('ok', 'revise', 'hold')",
            name=op.f("ck_reviews_verdict"),
        ),
        sa.CheckConstraint(
            "flags <@ ARRAY['urgent', 'caution', 'alternative']::text[]",
            name=op.f("ck_reviews_flags"),
        ),
        sa.CheckConstraint(
            "hold_reasons <@ "
            "ARRAY['part_unresolved', 'supplier_unresolved', 'no_demand_data']::text[]",
            name=op.f("ck_reviews_hold_reasons"),
        ),
        sa.CheckConstraint(
            "(entry = 'staff_request') = (requested_by IS NOT NULL)",
            name=op.f("ck_reviews_requester"),
        ),
        sa.CheckConstraint(
            "(decided_at IS NULL) = (decided_by IS NULL)", name=op.f("ck_reviews_decided_pair")
        ),
        _fk("reviews", "company_id", "companies.id", ondelete="CASCADE"),
        _fk("reviews", "part_id", "parts.id"),
        _fk("reviews", "requested_by", "users.id"),
        _fk("reviews", "source_message_id", "chat_messages.id"),
        _fk("reviews", "decided_by", "users.id"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reviews")),
    )
    op.create_index("ix_reviews_company_status", "reviews", ["company_id", "status"])
    op.create_index("ix_reviews_company_part", "reviews", ["company_id", "part_id"])

    op.create_table(
        "review_snapshots",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("company_id", sa.UUID(), nullable=False),
        sa.Column("review_id", sa.UUID(), nullable=False),
        sa.Column("hash", sa.String(length=80), nullable=False),
        sa.Column("values", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("settings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        _fk("review_snapshots", "company_id", "companies.id", ondelete="CASCADE"),
        _fk("review_snapshots", "review_id", "reviews.id", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_review_snapshots")),
    )
    op.create_index(
        "ix_review_snapshots_review_created", "review_snapshots", ["review_id", "created_at"]
    )

    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} TO bjk_app "
            "USING (company_id = app_company_id()) WITH CHECK (company_id = app_company_id())"
        )


def downgrade() -> None:
    for table in TABLES:
        op.execute(f"DROP POLICY tenant_isolation ON {table}")
    op.drop_index("ix_review_snapshots_review_created", table_name="review_snapshots")
    op.drop_table("review_snapshots")
    op.drop_index("ix_reviews_company_part", table_name="reviews")
    op.drop_index("ix_reviews_company_status", table_name="reviews")
    op.drop_table("reviews")
