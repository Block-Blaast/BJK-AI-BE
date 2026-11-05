"""purchase orders

Revision ID: 0026
Revises: 0025
Create Date: 2026-11-05 23:00:00.000000

발주 (API 명세서 PO-01~04, 기능명세서 16장 purchase_orders). 원장 movements.po_id에 외래 키를 건다.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0026"
down_revision: str | Sequence[str] | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _fk(column: str, target: str, **kwargs) -> sa.ForeignKeyConstraint:
    ref_table = target.split(".")[0]
    return sa.ForeignKeyConstraint(
        [column], [target], name=op.f(f"fk_purchase_orders_{column}_{ref_table}"), **kwargs
    )


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "purchase_orders",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("company_id", sa.UUID(), nullable=False),
        sa.Column("review_id", sa.UUID(), nullable=True),
        sa.Column("part_id", sa.UUID(), nullable=False),
        sa.Column("supplier_id", sa.UUID(), nullable=False),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), server_default="approved", nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_by", sa.UUID(), nullable=True),
        sa.Column("ordered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ordered_by", sa.UUID(), nullable=True),
        sa.Column("implicit_order", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("received_qty", sa.Integer(), server_default="0", nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('approved', 'ordered', 'partially_received', 'received', 'cancelled')",
            name=op.f("ck_purchase_orders_status"),
        ),
        sa.CheckConstraint("qty > 0", name=op.f("ck_purchase_orders_qty_positive")),
        sa.CheckConstraint("unit_price >= 0", name=op.f("ck_purchase_orders_unit_price")),
        sa.CheckConstraint("received_qty >= 0", name=op.f("ck_purchase_orders_received_qty")),
        sa.CheckConstraint(
            "(ordered_at IS NULL) = (ordered_by IS NULL)",
            name=op.f("ck_purchase_orders_ordered_pair"),
        ),
        _fk("company_id", "companies.id", ondelete="CASCADE"),
        _fk("review_id", "reviews.id"),
        _fk("part_id", "parts.id"),
        _fk("supplier_id", "suppliers.id"),
        _fk("approved_by", "users.id"),
        _fk("ordered_by", "users.id"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_purchase_orders")),
    )
    op.create_index(
        op.f("ix_purchase_orders_company_id"), "purchase_orders", ["company_id"], unique=False
    )
    op.create_index(
        "ix_purchase_orders_company_part_status",
        "purchase_orders",
        ["company_id", "part_id", "status"],
    )
    op.create_index(
        "ix_purchase_orders_company_status", "purchase_orders", ["company_id", "status"]
    )
    op.create_foreign_key(
        op.f("fk_movements_po_id_purchase_orders"),
        "movements",
        "purchase_orders",
        ["po_id"],
        ["id"],
    )
    op.execute("ALTER TABLE purchase_orders ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON purchase_orders TO bjk_app "
        "USING (company_id = app_company_id()) WITH CHECK (company_id = app_company_id())"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP POLICY tenant_isolation ON purchase_orders")
    op.drop_constraint(op.f("fk_movements_po_id_purchase_orders"), "movements", type_="foreignkey")
    op.drop_index("ix_purchase_orders_company_status", table_name="purchase_orders")
    op.drop_index("ix_purchase_orders_company_part_status", table_name="purchase_orders")
    op.drop_index(op.f("ix_purchase_orders_company_id"), table_name="purchase_orders")
    op.drop_table("purchase_orders")
