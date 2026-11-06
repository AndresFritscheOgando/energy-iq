"""Published tariff schedules and the invoice tariff class. Revision ID: 0006."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "invoice_revisions", sa.Column("tariff_class", sa.Text(), nullable=True)
    )
    op.create_check_constraint(
        op.f("ck_invoice_revisions_tariff_class_format"),
        "invoice_revisions",
        "tariff_class ~ '^[A-Z0-9][A-Z0-9-]{0,15}$'",
    )
    op.create_table(
        "tariff_schedules",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("distributor", sa.Text(), nullable=False),
        sa.Column("tariff_class", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("effective_start", sa.Date(), nullable=False),
        sa.Column("effective_end", sa.Date(), nullable=False),
        sa.Column(
            "effective_daterange",
            postgresql.DATERANGE(),
            sa.Computed(
                "daterange(effective_start, effective_end, '[]')", persisted=True
            ),
        ),
        sa.Column("resolution_id", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("source_digest", sa.Text(), nullable=False),
        sa.Column("published_on", sa.Date(), nullable=False),
        sa.Column("checked_on", sa.Date(), nullable=False),
        sa.Column("checked_by", sa.Text(), nullable=False),
        sa.Column("rounding_places", sa.Integer(), nullable=False),
        sa.Column("rounding_mode", sa.Text(), nullable=False),
        sa.Column("rounding_scope", sa.Text(), nullable=False),
        sa.Column("manifest_revision", sa.Text(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "distributor", "tariff_class", "version", name="uq_tariff_schedules_version"
        ),
        sa.UniqueConstraint(
            "distributor",
            "tariff_class",
            "resolution_id",
            name="uq_tariff_schedules_resolution",
        ),
        postgresql.ExcludeConstraint(
            ("distributor", "="),
            ("tariff_class", "="),
            ("effective_daterange", "&&"),
            name="ex_tariff_schedules_overlap",
            using="gist",
        ),
        sa.CheckConstraint(
            "effective_end >= effective_start",
            name=op.f("ck_tariff_schedules_effective_order"),
        ),
        sa.CheckConstraint(
            "checked_on >= published_on", name=op.f("ck_tariff_schedules_checked_order")
        ),
        sa.CheckConstraint(
            "source_digest ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_tariff_schedules_digest_format"),
        ),
        sa.CheckConstraint(
            "distributor IN ('EDESUR', 'EDEESTE', 'EDENORTE')",
            name=op.f("ck_tariff_schedules_distributor"),
        ),
        sa.CheckConstraint(
            "tariff_class = 'BTS-1'", name=op.f("ck_tariff_schedules_class_supported")
        ),
        sa.CheckConstraint(
            "rounding_places BETWEEN 0 AND 6",
            name=op.f("ck_tariff_schedules_rounding_places"),
        ),
        sa.CheckConstraint(
            "rounding_mode IN ('half_up', 'half_even', 'up', 'down')",
            name=op.f("ck_tariff_schedules_rounding_mode"),
        ),
        sa.CheckConstraint(
            "rounding_scope IN ('total', 'per_band')",
            name=op.f("ck_tariff_schedules_rounding_scope"),
        ),
    )
    op.create_table(
        "tariff_bands",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "schedule_id",
            sa.Uuid(),
            sa.ForeignKey(
                "tariff_schedules.id",
                ondelete="RESTRICT",
                name="fk_tariff_bands_schedule",
            ),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("charge_type", sa.Text(), nullable=False),
        sa.Column("from_kwh", sa.Numeric(18, 6), nullable=False),
        sa.Column("to_kwh", sa.Numeric(18, 6), nullable=True),
        sa.Column("amount", sa.Numeric(18, 6), nullable=False),
        sa.UniqueConstraint("schedule_id", "position", name="uq_tariff_bands_position"),
        sa.CheckConstraint(
            "charge_type IN ('energy_slice', 'energy_all_kwh', 'fixed_range')",
            name=op.f("ck_tariff_bands_charge_type"),
        ),
        sa.CheckConstraint(
            "from_kwh >= 0 AND amount >= 0", name=op.f("ck_tariff_bands_nonnegative")
        ),
        sa.CheckConstraint(
            "to_kwh IS NULL OR to_kwh >= from_kwh",
            name=op.f("ck_tariff_bands_range_order"),
        ),
    )
    op.create_index("ix_tariff_bands_schedule_id", "tariff_bands", ["schedule_id"])
    op.execute(
        """
        CREATE FUNCTION tariff_rows_are_immutable() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'published tariff rows are immutable'
                USING ERRCODE = 'integrity_constraint_violation';
        END;
        $$
        """
    )
    for table in ("tariff_schedules", "tariff_bands"):
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table}"
            " FOR EACH ROW EXECUTE FUNCTION tariff_rows_are_immutable()"
        )
    op.execute("GRANT SELECT ON tariff_schedules, tariff_bands TO energyiq_app")


def downgrade() -> None:
    op.execute("REVOKE ALL ON tariff_bands, tariff_schedules FROM energyiq_app")
    op.drop_table("tariff_bands")
    op.drop_table("tariff_schedules")
    op.execute("DROP FUNCTION tariff_rows_are_immutable()")
    op.drop_constraint(
        op.f("ck_invoice_revisions_tariff_class_format"),
        "invoice_revisions",
        type_="check",
    )
    op.drop_column("invoice_revisions", "tariff_class")
