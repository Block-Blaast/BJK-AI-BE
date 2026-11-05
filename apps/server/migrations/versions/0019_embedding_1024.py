"""embedding 1024

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-05 18:10:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0019"
down_revision: str | Sequence[str] | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# ai 임베딩(Bedrock Titan Text Embeddings V2)은 1024차원이다 (bjk_contracts.EMBEDDING_DIM).
# main 배포 DB는 0012를 1024로 고친 뒤 만들어져 이미 1024라 그대로 둔다.
# 이전 0012(1536)로 만든 DB만 바꾼다. 차원이 다른 벡터는 바꿀 수 없어 지우고, nightly가 다시 채운다.
EMBEDDING_DIM = 1024
TABLES = ("parts", "part_aliases")


def _dimension(table: str) -> int:
    # vector 열의 atttypmod가 차원이다.
    return op.get_bind().scalar(
        sa.text(
            "SELECT atttypmod FROM pg_attribute "
            "WHERE attrelid = CAST(:t AS regclass) AND attname = 'embedding'"
        ),
        {"t": table},
    )


def upgrade() -> None:
    """Upgrade schema."""
    for table in TABLES:
        if _dimension(table) == EMBEDDING_DIM:
            continue
        op.execute(f"UPDATE {table} SET embedding = NULL, embedding_model = NULL")
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN embedding TYPE vector({EMBEDDING_DIM}) USING NULL"
        )


def downgrade() -> None:
    """Downgrade schema."""
    # 0012가 1024로 만들므로 되돌릴 차원이 없다.
