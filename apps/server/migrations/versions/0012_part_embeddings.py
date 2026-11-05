"""part embeddings

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-05 10:20:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision: str = "0012"
down_revision: str | Sequence[str] | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# bjk_contracts.embedding.EMBEDDING_DIM과 같게 둔다.
EMBEDDING_DIM = 1536
TABLES = ("parts", "part_aliases")


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    for table in TABLES:
        op.add_column(table, sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True))
        # 모델이 다른 벡터끼리는 비교할 수 없어 벡터를 만든 모델명을 함께 저장한다.
        op.add_column(table, sa.Column("embedding_model", sa.String(length=100), nullable=True))
        op.create_check_constraint(
            op.f(f"ck_{table}_embedding_model"),
            table,
            "(embedding IS NULL) = (embedding_model IS NULL)",
        )


def downgrade() -> None:
    """Downgrade schema."""
    for table in TABLES:
        op.drop_constraint(op.f(f"ck_{table}_embedding_model"), table, type_="check")
        op.drop_column(table, "embedding_model")
        op.drop_column(table, "embedding")
    op.execute("DROP EXTENSION IF EXISTS vector")
