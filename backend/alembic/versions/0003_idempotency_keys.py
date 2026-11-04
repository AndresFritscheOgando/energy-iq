"""Stored POST retry keys. Revision ID: 0003; Revises: 0002."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "idempotency_keys",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("operation", sa.Text(), nullable=False),
        sa.Column("request_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("response_status", sa.SmallInteger(), nullable=True),
        sa.Column("response_body", sa.LargeBinary(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "key", name="pk_idempotency_keys"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_idempotency_keys_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "char_length(key) BETWEEN 1 AND 255",
            name=op.f("ck_idempotency_keys_key_length"),
        ),
        sa.CheckConstraint(
            "octet_length(request_hash) = 32",
            name=op.f("ck_idempotency_keys_request_hash_length"),
        ),
        sa.CheckConstraint(
            "(response_status IS NULL) = (response_body IS NULL)",
            name=op.f("ck_idempotency_keys_response_pair"),
        ),
    )
    op.create_index(
        "ix_idempotency_keys_expires_at", "idempotency_keys", ["expires_at"]
    )
    op.execute("GRANT SELECT, INSERT, UPDATE ON idempotency_keys TO energyiq_app")


def downgrade() -> None:
    op.execute("REVOKE ALL ON idempotency_keys FROM energyiq_app")
    op.drop_table("idempotency_keys")
