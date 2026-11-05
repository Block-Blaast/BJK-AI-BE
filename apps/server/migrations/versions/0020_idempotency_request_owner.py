"""Bind idempotency records to the requester and request content.

Revision ID: 0020
Revises: 0019
"""

import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 기존 기록은 소유자와 요청 내용을 복원할 수 없어 NULL로 남기고 재생을 차단한다.
    op.add_column("idempotency_keys", sa.Column("user_id", sa.UUID(), nullable=True))
    op.add_column("idempotency_keys", sa.Column("request_hash", sa.String(64), nullable=True))
    op.create_foreign_key(
        "fk_idempotency_keys_user_id_users",
        "idempotency_keys",
        "users",
        ["user_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_idempotency_keys_user_id_users", "idempotency_keys", type_="foreignkey")
    op.drop_column("idempotency_keys", "request_hash")
    op.drop_column("idempotency_keys", "user_id")
