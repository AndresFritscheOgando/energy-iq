"""Private source documents and extraction runs. Revision ID: 0005."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _fk(target: str, name: str | None = None) -> sa.ForeignKey:
    return sa.ForeignKey(target, ondelete="RESTRICT", name=name)


def upgrade() -> None:
    op.create_table(
        "source_documents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("owner_id", sa.Uuid(), _fk("users.id"), nullable=False),
        sa.Column("property_id", sa.Uuid(), _fk("properties.id"), nullable=False),
        sa.Column("meter_id", sa.Uuid(), _fk("meters.id"), nullable=False),
        sa.Column("storage_key", sa.Uuid(), nullable=False),
        sa.Column("sha256", sa.LargeBinary(32), nullable=False),
        sa.Column("mime_type", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("purged_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("storage_key", name="uq_source_documents_storage_key"),
        sa.CheckConstraint(
            "octet_length(sha256) = 32", name=op.f("ck_source_documents_sha256_length")
        ),
        sa.CheckConstraint(
            "mime_type = 'application/pdf'",
            name=op.f("ck_source_documents_mime_type"),
        ),
        sa.CheckConstraint(
            "size_bytes > 0", name=op.f("ck_source_documents_size_positive")
        ),
        sa.CheckConstraint(
            "purged_at IS NULL OR deleted_at IS NOT NULL",
            name=op.f("ck_source_documents_purge_after_delete"),
        ),
    )
    op.create_index("ix_source_documents_owner_id", "source_documents", ["owner_id"])
    op.create_index(
        "ix_source_documents_property_id", "source_documents", ["property_id"]
    )
    op.create_index("ix_source_documents_meter_id", "source_documents", ["meter_id"])
    op.create_table(
        "extraction_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "document_id",
            sa.Uuid(),
            _fk("source_documents.id", "fk_runs_document"),
            nullable=False,
        ),
        sa.Column("run_number", sa.Integer(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column(
            "attempts", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("lease_owner", sa.Text(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("prompt_version", sa.Text(), nullable=True),
        sa.Column("output", postgresql.JSONB(), nullable=True),
        sa.UniqueConstraint(
            "document_id", "run_number", name="uq_extraction_runs_number"
        ),
        sa.CheckConstraint(
            "state IN ('queued', 'running', 'succeeded', 'failed')",
            name=op.f("ck_extraction_runs_state"),
        ),
        sa.CheckConstraint(
            "attempts >= 0", name=op.f("ck_extraction_runs_attempts_nonnegative")
        ),
        sa.CheckConstraint(
            "state <> 'running' OR (lease_owner IS NOT NULL"
            " AND lease_expires_at IS NOT NULL)",
            name=op.f("ck_extraction_runs_running_has_lease"),
        ),
        sa.CheckConstraint(
            "state <> 'failed' OR error_code IS NOT NULL",
            name=op.f("ck_extraction_runs_failed_has_code"),
        ),
    )
    op.create_index(
        "ix_extraction_runs_document_id", "extraction_runs", ["document_id"]
    )
    op.create_index(
        "uq_extraction_runs_active_document",
        "extraction_runs",
        ["document_id"],
        unique=True,
        postgresql_where=sa.text("state IN ('queued', 'running')"),
    )
    op.create_index(
        "ix_extraction_runs_claim",
        "extraction_runs",
        ["state", "lease_expires_at", "created_at"],
    )
    op.create_foreign_key(
        "fk_invoice_revisions_source_document",
        "invoice_revisions",
        "source_documents",
        ["source_document_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_invoice_revisions_source_document_id",
        "invoice_revisions",
        ["source_document_id"],
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE (deleted_at, purged_at)"
        " ON source_documents TO energyiq_app"
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE (state, attempts, lease_owner,"
        " lease_expires_at, error_code, started_at, finished_at, model,"
        " prompt_version, output) ON extraction_runs TO energyiq_app"
    )


def downgrade() -> None:
    op.execute("REVOKE ALL ON extraction_runs FROM energyiq_app")
    op.execute("REVOKE ALL ON source_documents FROM energyiq_app")
    op.drop_index("ix_invoice_revisions_source_document_id", "invoice_revisions")
    op.drop_constraint(
        "fk_invoice_revisions_source_document", "invoice_revisions", type_="foreignkey"
    )
    op.drop_table("extraction_runs")
    op.drop_table("source_documents")
