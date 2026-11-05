"""embedding 1024

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-05 18:10:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0019"
down_revision: str | Sequence[str] | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# ai 임베딩(Bedrock Titan Text Embeddings V2)은 1024차원이다 (bjk_contracts.EMBEDDING_DIM).
# 차원이 다른 벡터는 바꿀 수 없어 지우고, nightly가 새 모델로 다시 채운다.
TABLES = ("parts", "part_aliases")


def _resize(dim: int) -> None:
    for table in TABLES:
        op.execute(f"UPDATE {table} SET embedding = NULL, embedding_model = NULL")
        op.execute(f"ALTER TABLE {table} ALTER COLUMN embedding TYPE vector({dim}) USING NULL")


def upgrade() -> None:
    """Upgrade schema."""
    _resize(1024)


def downgrade() -> None:
    """Downgrade schema."""
    _resize(1536)
