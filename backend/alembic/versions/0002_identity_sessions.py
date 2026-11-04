"""Identity: sessions and auth attempts.

Revision ID: 0002
Revises: 0001
Created: 2026-11-04

Hand reviewed (spec 0009/0002 AC-3, AC-6, AC-12). Both tables are new and
empty, so plain CREATE INDEX is safe. Names follow the umbrella convention.

Privileges (AC-12): energyiq_app may SELECT and INSERT on both tables and
UPDATE only ``sessions.last_seen_at`` and ``sessions.revoked_at``. It may
never DELETE: expired rows are purged by the maintenance command as the
migrator role. downgrade() revokes everything it granted.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "energyiq_app"
TABLES = ("sessions", "auth_attempts")
SESSION_UPDATES = ("last_seen_at", "revoked_at")
IDENTITY_SEQUENCES = ("auth_attempts_id_seq",)


def _timestamp(name: str, *, nullable: bool = False) -> sa.Column[object]:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def upgrade() -> None:
    op.create_table(
        "sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(), nullable=False),
        _timestamp("created_at"),
        _timestamp("last_seen_at"),
        _timestamp("expires_at"),
        _timestamp("revoked_at", nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_sessions"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_sessions_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("token_hash", name="uq_sessions_token_hash"),
        sa.CheckConstraint(
            "octet_length(token_hash) = 32",
            name=op.f("ck_sessions_token_hash_length"),
        ),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])

    op.create_table(
        "auth_attempts",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("email_key", sa.LargeBinary(), nullable=True),
        sa.Column("client_key", sa.LargeBinary(), nullable=False),
        sa.Column("succeeded", sa.Boolean(), nullable=False),
        _timestamp("attempted_at"),
        sa.PrimaryKeyConstraint("id", name="pk_auth_attempts"),
        sa.CheckConstraint(
            "kind IN ('login', 'register')", name=op.f("ck_auth_attempts_kind")
        ),
    )
    op.create_index(
        "ix_auth_attempts_email_key", "auth_attempts", ["email_key", "attempted_at"]
    )
    op.create_index(
        "ix_auth_attempts_client_key", "auth_attempts", ["client_key", "attempted_at"]
    )

    for table in TABLES:
        op.execute(f"GRANT SELECT, INSERT ON {table} TO {APP_ROLE}")
    op.execute(f"GRANT UPDATE ({', '.join(SESSION_UPDATES)}) ON sessions TO {APP_ROLE}")
    for sequence in IDENTITY_SEQUENCES:
        op.execute(f"GRANT USAGE ON SEQUENCE {sequence} TO {APP_ROLE}")


def downgrade() -> None:
    for sequence in IDENTITY_SEQUENCES:
        op.execute(f"REVOKE ALL ON SEQUENCE {sequence} FROM {APP_ROLE}")
    for table in TABLES:
        op.execute(f"REVOKE ALL ON {table} FROM {APP_ROLE}")
    for table in reversed(TABLES):
        op.drop_table(table)
