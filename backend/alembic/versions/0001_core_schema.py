"""Core schema: users, properties, meters, meter events, readings, audit events.

Revision ID: 0001
Revises:
Created: 2026-11-04

Hand reviewed (spec 0009/0001 AC-2). The tables are new and empty, so plain
CREATE INDEX and validated constraints are safe here. Every name follows the
umbrella naming convention so IntegrityError maps to a problem code by name.

Privileges (AC-1): energyiq_app may SELECT and INSERT on every table, UPDATE
only the listed columns, and never DELETE, TRUNCATE, or run DDL. downgrade()
revokes everything it granted.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "energyiq_app"
TABLES = ("users", "properties", "meters", "meter_events", "readings", "audit_events")
COLUMN_UPDATES: dict[str, tuple[str, ...]] = {
    "users": ("password_hash", "disabled_at"),
    "properties": ("nickname", "region", "timezone", "updated_at", "archived_at"),
    "meters": ("label", "register_digits", "active", "deactivated_at", "updated_at"),
    "readings": ("status", "status_changed_at"),
    "meter_events": ("status", "decided_by", "decided_at"),
}
IDENTITY_SEQUENCES = ("audit_events_id_seq",)


def _timestamp(name: str, *, nullable: bool = False) -> sa.Column[object]:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        _timestamp("created_at"),
        _timestamp("disabled_at", nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.CheckConstraint(
            "char_length(email) <= 254", name=op.f("ck_users_email_length")
        ),
    )

    op.create_table(
        "properties",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("nickname", sa.Text(), nullable=False),
        sa.Column("region", sa.Text(), nullable=True),
        sa.Column(
            "timezone",
            sa.Text(),
            server_default=sa.text("'America/Santo_Domingo'"),
            nullable=False,
        ),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        _timestamp("archived_at", nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_properties"),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name="fk_properties_owner_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "char_length(nickname) BETWEEN 1 AND 80",
            name=op.f("ck_properties_nickname_length"),
        ),
        sa.CheckConstraint(
            "char_length(region) <= 80", name=op.f("ck_properties_region_length")
        ),
        sa.CheckConstraint(
            "char_length(timezone) BETWEEN 1 AND 64",
            name=op.f("ck_properties_timezone_length"),
        ),
    )
    op.create_index("ix_properties_owner_user_id", "properties", ["owner_user_id"])
    op.create_index(
        "uq_properties_owner_nickname_active",
        "properties",
        ["owner_user_id", sa.text("lower(nickname)")],
        unique=True,
        postgresql_where=sa.text("archived_at IS NULL"),
    )

    op.create_table(
        "meters",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("property_id", sa.Uuid(), nullable=False),
        sa.Column("distributor", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("register_digits", sa.SmallInteger(), nullable=True),
        sa.Column(
            "active", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        _timestamp("deactivated_at", nullable=True),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        sa.PrimaryKeyConstraint("id", name="pk_meters"),
        sa.ForeignKeyConstraint(
            ["property_id"],
            ["properties.id"],
            name="fk_meters_property_id_properties",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "distributor IN ('EDESUR', 'EDEESTE', 'EDENORTE', 'OTHER')",
            name=op.f("ck_meters_distributor"),
        ),
        sa.CheckConstraint(
            "char_length(label) BETWEEN 1 AND 60", name=op.f("ck_meters_label_length")
        ),
        sa.CheckConstraint(
            "register_digits BETWEEN 4 AND 9",
            name=op.f("ck_meters_register_digits_range"),
        ),
        sa.CheckConstraint(
            "active = (deactivated_at IS NULL)",
            name=op.f("ck_meters_active_deactivated"),
        ),
    )
    op.create_index("ix_meters_property_id", "meters", ["property_id"])
    op.create_index(
        "uq_meters_property_label_active",
        "meters",
        ["property_id", sa.text("lower(label)")],
        unique=True,
        postgresql_where=sa.text("active"),
    )

    op.create_table(
        "meter_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("meter_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        _timestamp("effective_at"),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        _timestamp("created_at"),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        _timestamp("decided_at", nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_meter_events"),
        sa.ForeignKeyConstraint(
            ["meter_id"],
            ["meters.id"],
            name="fk_meter_events_meter_id_meters",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name="fk_meter_events_created_by_users",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["decided_by"],
            ["users.id"],
            name="fk_meter_events_decided_by_users",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "event_type IN ('installed', 'reset', 'replaced', 'rollover',"
            " 'calibration')",
            name=op.f("ck_meter_events_event_type"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')",
            name=op.f("ck_meter_events_status"),
        ),
        sa.CheckConstraint(
            "char_length(note) <= 500", name=op.f("ck_meter_events_note_length")
        ),
        sa.CheckConstraint(
            "(status = 'pending' AND decided_by IS NULL AND decided_at IS NULL)"
            " OR (status <> 'pending'"
            " AND decided_by IS NOT NULL AND decided_at IS NOT NULL)",
            name=op.f("ck_meter_events_decision_pair"),
        ),
    )
    op.create_index("ix_meter_events_created_by", "meter_events", ["created_by"])
    op.create_index("ix_meter_events_decided_by", "meter_events", ["decided_by"])
    op.create_index(
        "ix_meter_events_meter_effective",
        "meter_events",
        ["meter_id", "effective_at", "id"],
    )

    op.create_table(
        "readings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("meter_id", sa.Uuid(), nullable=False),
        _timestamp("recorded_at"),
        sa.Column("original_local_date", sa.Date(), nullable=True),
        sa.Column("cumulative_kwh", sa.Numeric(18, 6), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        _timestamp("created_at"),
        _timestamp("status_changed_at", nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_readings"),
        sa.ForeignKeyConstraint(
            ["meter_id"],
            ["meters.id"],
            name="fk_readings_meter_id_meters",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name="fk_readings_created_by_users",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "cumulative_kwh >= 0", name=op.f("ck_readings_cumulative_kwh_nonnegative")
        ),
        sa.CheckConstraint(
            "source IN ('manual', 'import')", name=op.f("ck_readings_source")
        ),
        sa.CheckConstraint(
            "status IN ('valid', 'flagged', 'voided')", name=op.f("ck_readings_status")
        ),
    )
    op.create_index("ix_readings_created_by", "readings", ["created_by"])
    op.create_index(
        "ix_readings_meter_recorded", "readings", ["meter_id", "recorded_at", "id"]
    )
    op.create_index(
        "uq_readings_meter_instant_active",
        "readings",
        ["meter_id", "recorded_at"],
        unique=True,
        postgresql_where=sa.text("status <> 'voided'"),
    )

    op.create_table(
        "audit_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=True),
        _timestamp("occurred_at"),
        sa.Column("request_id", sa.Text(), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_audit_events"),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name="fk_audit_events_actor_user_id_users",
            ondelete="RESTRICT",
        ),
    )
    op.create_index("ix_audit_events_actor_user_id", "audit_events", ["actor_user_id"])
    op.create_index(
        "ix_audit_events_entity", "audit_events", ["entity_type", "entity_id"]
    )

    _grant()


def _grant() -> None:
    for table in TABLES:
        op.execute(f"GRANT SELECT, INSERT ON {table} TO {APP_ROLE}")
    for table, columns in COLUMN_UPDATES.items():
        op.execute(f"GRANT UPDATE ({', '.join(columns)}) ON {table} TO {APP_ROLE}")
    for sequence in IDENTITY_SEQUENCES:
        op.execute(f"GRANT USAGE ON SEQUENCE {sequence} TO {APP_ROLE}")
    # Readiness compares the stamped revision with the code's head.
    op.execute(f"GRANT SELECT ON alembic_version TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE ALL ON alembic_version FROM {APP_ROLE}")
    for sequence in IDENTITY_SEQUENCES:
        op.execute(f"REVOKE ALL ON SEQUENCE {sequence} FROM {APP_ROLE}")
    for table in TABLES:
        op.execute(f"REVOKE ALL ON {table} FROM {APP_ROLE}")

    for table in reversed(TABLES):
        op.drop_table(table)
