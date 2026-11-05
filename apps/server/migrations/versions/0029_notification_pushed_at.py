"""notification pushed at

Revision ID: 0029
Revises: 0028
Create Date: 2026-11-06 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0029"
down_revision: str | Sequence[str] | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """웹 푸시 발송 시도 시각. 비어 있으면 아직 보내지 않은 알림이다."""
    op.add_column("notifications", sa.Column("pushed_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("notifications", "pushed_at")
