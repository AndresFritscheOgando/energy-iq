"""Invoice rows for spec 0012 child 0001."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import DATERANGE, JSONB, ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column

from energyiq.platform.db import Base, in_values


class InvoiceRow(Base):
    __tablename__ = "invoices"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    meter_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("meters.id", ondelete="RESTRICT"), index=True
    )
    owner_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    current_revision_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey(
            "invoice_revisions.id",
            ondelete="RESTRICT",
            use_alter=True,
            name="fk_invoices_current_revision",
        ),
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class InvoiceRevisionRow(Base):
    __tablename__ = "invoice_revisions"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    invoice_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "invoices.id", ondelete="RESTRICT", name="fk_invoice_revisions_invoice"
        ),
        index=True,
    )
    revision_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text)
    actor_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="RESTRICT", name="fk_invoice_revisions_actor"),
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    distributor: Mapped[str | None] = mapped_column(Text)
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    billed_kwh: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    total_dop: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    energy_charge_dop: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    issue_date: Mapped[date | None] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date)
    source_document_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey(
            "source_documents.id",
            ondelete="RESTRICT",
            name="fk_invoice_revisions_source_document",
        ),
        index=True,
    )
    field_origins: Mapped[dict[str, str]] = mapped_column(JSONB)
    previous_revision_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey(
            "invoice_revisions.id",
            ondelete="RESTRICT",
            name="fk_invoice_revisions_previous",
        ),
        index=True,
    )
    changed_fields: Mapped[list[str]] = mapped_column(JSONB)
    old_values: Mapped[dict[str, str | None]] = mapped_column(JSONB)

    __table_args__ = (
        UniqueConstraint(
            "invoice_id", "revision_number", name="uq_invoice_revisions_number"
        ),
        CheckConstraint(in_values("status", ("draft", "confirmed")), name="status"),
        CheckConstraint("period_end >= period_start", name="period_order"),
        CheckConstraint("billed_kwh >= 0", name="billed_kwh_nonnegative"),
        CheckConstraint("total_dop >= 0", name="total_nonnegative"),
        CheckConstraint("energy_charge_dop >= 0", name="energy_nonnegative"),
    )


class InvoiceCurrentPeriodRow(Base):
    __tablename__ = "invoice_current_periods"

    invoice_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "invoices.id", ondelete="RESTRICT", name="fk_invoice_periods_invoice"
        ),
        primary_key=True,
    )
    meter_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("meters.id", ondelete="RESTRICT", name="fk_invoice_periods_meter"),
        index=True,
    )
    current_revision_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "invoice_revisions.id",
            ondelete="RESTRICT",
            name="fk_invoice_periods_revision",
        ),
        index=True,
    )
    local_daterange: Mapped[object] = mapped_column(DATERANGE)

    __table_args__ = (
        ExcludeConstraint(
            (meter_id, "="),
            (local_daterange, "&&"),
            name="ex_invoice_current_periods_meter_overlap",
            using="gist",
        ),
    )
