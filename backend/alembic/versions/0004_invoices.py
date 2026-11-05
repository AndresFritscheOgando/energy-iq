"""Manual invoices and immutable revision history. Revision ID: 0004."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.create_table(
        "invoices",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "meter_id",
            sa.Uuid(),
            sa.ForeignKey("meters.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "owner_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("current_revision_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_invoices_meter_id", "invoices", ["meter_id"])
    op.create_index("ix_invoices_owner_id", "invoices", ["owner_id"])
    op.create_index(
        "ix_invoices_current_revision_id", "invoices", ["current_revision_id"]
    )
    op.create_table(
        "invoice_revisions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "invoice_id",
            sa.Uuid(),
            sa.ForeignKey(
                "invoices.id", ondelete="RESTRICT", name="fk_invoice_revisions_invoice"
            ),
            nullable=False,
        ),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "actor_id",
            sa.Uuid(),
            sa.ForeignKey(
                "users.id", ondelete="RESTRICT", name="fk_invoice_revisions_actor"
            ),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("distributor", sa.Text(), nullable=True),
        sa.Column("period_start", sa.Date(), nullable=True),
        sa.Column("period_end", sa.Date(), nullable=True),
        sa.Column("billed_kwh", sa.Numeric(18, 6), nullable=True),
        sa.Column("total_dop", sa.Numeric(16, 2), nullable=True),
        sa.Column("energy_charge_dop", sa.Numeric(16, 2), nullable=True),
        sa.Column("issue_date", sa.Date(), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("source_document_id", sa.Uuid(), nullable=True),
        sa.Column("field_origins", postgresql.JSONB(), nullable=False),
        sa.Column(
            "previous_revision_id",
            sa.Uuid(),
            sa.ForeignKey(
                "invoice_revisions.id",
                ondelete="RESTRICT",
                name="fk_invoice_revisions_previous",
            ),
            nullable=True,
        ),
        sa.Column("changed_fields", postgresql.JSONB(), nullable=False),
        sa.Column("old_values", postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint(
            "invoice_id", "revision_number", name="uq_invoice_revisions_number"
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'confirmed')", name=op.f("ck_invoice_revisions_status")
        ),
        sa.CheckConstraint(
            "period_end >= period_start", name=op.f("ck_invoice_revisions_period_order")
        ),
        sa.CheckConstraint(
            "billed_kwh >= 0", name=op.f("ck_invoice_revisions_billed_kwh_nonnegative")
        ),
        sa.CheckConstraint(
            "total_dop >= 0", name=op.f("ck_invoice_revisions_total_nonnegative")
        ),
        sa.CheckConstraint(
            "energy_charge_dop >= 0",
            name=op.f("ck_invoice_revisions_energy_nonnegative"),
        ),
    )
    op.create_index(
        "ix_invoice_revisions_invoice_id", "invoice_revisions", ["invoice_id"]
    )
    op.create_index("ix_invoice_revisions_actor_id", "invoice_revisions", ["actor_id"])
    op.create_index(
        "ix_invoice_revisions_previous_revision_id",
        "invoice_revisions",
        ["previous_revision_id"],
    )
    op.create_foreign_key(
        "fk_invoices_current_revision",
        "invoices",
        "invoice_revisions",
        ["current_revision_id"],
        ["id"],
        ondelete="RESTRICT",
        use_alter=True,
    )
    op.create_table(
        "invoice_current_periods",
        sa.Column(
            "invoice_id",
            sa.Uuid(),
            sa.ForeignKey(
                "invoices.id", ondelete="RESTRICT", name="fk_invoice_periods_invoice"
            ),
            primary_key=True,
        ),
        sa.Column(
            "meter_id",
            sa.Uuid(),
            sa.ForeignKey(
                "meters.id", ondelete="RESTRICT", name="fk_invoice_periods_meter"
            ),
            nullable=False,
        ),
        sa.Column(
            "current_revision_id",
            sa.Uuid(),
            sa.ForeignKey(
                "invoice_revisions.id",
                ondelete="RESTRICT",
                name="fk_invoice_periods_revision",
            ),
            nullable=False,
        ),
        sa.Column("local_daterange", postgresql.DATERANGE(), nullable=False),
        postgresql.ExcludeConstraint(
            ("meter_id", "="),
            ("local_daterange", "&&"),
            name="ex_invoice_current_periods_meter_overlap",
            using="gist",
        ),
    )
    op.create_index(
        "ix_invoice_current_periods_meter_id", "invoice_current_periods", ["meter_id"]
    )
    op.create_index(
        "ix_invoice_current_periods_current_revision_id",
        "invoice_current_periods",
        ["current_revision_id"],
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE (current_revision_id) ON invoices TO energyiq_app"
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE (status, confirmed_at) ON invoice_revisions TO energyiq_app"
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE (current_revision_id, local_daterange) ON invoice_current_periods TO energyiq_app"
    )


def downgrade() -> None:
    op.execute("REVOKE ALL ON invoice_current_periods FROM energyiq_app")
    op.execute("REVOKE ALL ON invoice_revisions FROM energyiq_app")
    op.execute("REVOKE ALL ON invoices FROM energyiq_app")
    op.drop_table("invoice_current_periods")
    op.execute(
        "ALTER TABLE invoices DROP CONSTRAINT IF EXISTS fk_invoices_current_revision"
    )
    op.execute(
        "ALTER TABLE invoices DROP CONSTRAINT IF EXISTS fk_invoices_current_revision_id_invoice_revisions"
    )
    op.drop_table("invoice_revisions")
    op.drop_table("invoices")
    op.execute("DROP EXTENSION IF EXISTS btree_gist")
