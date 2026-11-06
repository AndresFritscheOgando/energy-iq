"""Document and extraction run rows (spec 0012 child 0002).

The document row is the tombstone: ``deleted_at`` is set in one transaction,
then the file is removed and ``purged_at`` records that it is gone. Its state
is derived from the latest run, never stored, so it cannot drift from the run.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from energyiq.platform.db import Base, in_values

RUN_STATES = ("queued", "running", "succeeded", "failed")
ACTIVE_RUN_STATES = ("queued", "running")


class SourceDocumentRow(Base):
    __tablename__ = "source_documents"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    property_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("properties.id", ondelete="RESTRICT"), index=True
    )
    meter_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("meters.id", ondelete="RESTRICT"), index=True
    )
    # The opaque name of the stored file; never returned by the API.
    storage_key: Mapped[UUID] = mapped_column(Uuid, unique=True)
    sha256: Mapped[bytes] = mapped_column(LargeBinary(32))
    mime_type: Mapped[str] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("octet_length(sha256) = 32", name="sha256_length"),
        CheckConstraint("mime_type = 'application/pdf'", name="mime_type"),
        CheckConstraint("size_bytes > 0", name="size_positive"),
        CheckConstraint(
            "purged_at IS NULL OR deleted_at IS NOT NULL", name="purge_after_delete"
        ),
    )


class ExtractionRunRow(Base):
    __tablename__ = "extraction_runs"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    document_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("source_documents.id", ondelete="RESTRICT", name="fk_runs_document"),
        index=True,
    )
    run_number: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    lease_owner: Mapped[str | None] = mapped_column(Text)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    model: Mapped[str | None] = mapped_column(Text)
    prompt_version: Mapped[str | None] = mapped_column(Text)
    output: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    __table_args__ = (
        UniqueConstraint("document_id", "run_number", name="uq_extraction_runs_number"),
        CheckConstraint(in_values("state", RUN_STATES), name="state"),
        CheckConstraint("attempts >= 0", name="attempts_nonnegative"),
        CheckConstraint(
            "state <> 'running' OR (lease_owner IS NOT NULL"
            " AND lease_expires_at IS NOT NULL)",
            name="running_has_lease",
        ),
        CheckConstraint(
            "state <> 'failed' OR error_code IS NOT NULL", name="failed_has_code"
        ),
        Index(
            "uq_extraction_runs_active_document",
            "document_id",
            unique=True,
            postgresql_where=text("state IN ('queued', 'running')"),
        ),
        Index("ix_extraction_runs_claim", "state", "lease_expires_at", "created_at"),
    )
