"""ORM rows for readings and meter events (spec 0009/0001 data model).

psycopg returns ``NUMERIC`` as ``Decimal`` and ``timestamptz`` as aware
datetimes; the row to domain mapping converts with ``.astimezone(UTC)``. No
float ever touches kWh.
"""

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    Text,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from energyiq.platform.db import Base, in_values
from energyiq.readings.models import MeterEventType, ReadingSource, ReadingStatus


class MeterEventStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class MeterEventRow(Base):
    """A reset, replacement, or other meter event awaiting or past review."""

    __tablename__ = "meter_events"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    meter_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("meters.id", ondelete="RESTRICT")
    )
    event_type: Mapped[str] = mapped_column(Text)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    decided_by: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(in_values("event_type", MeterEventType), name="event_type"),
        CheckConstraint(in_values("status", MeterEventStatus), name="status"),
        CheckConstraint("char_length(note) <= 500", name="note_length"),
        CheckConstraint(
            "(status = 'pending' AND decided_by IS NULL AND decided_at IS NULL)"
            " OR (status <> 'pending'"
            " AND decided_by IS NOT NULL AND decided_at IS NOT NULL)",
            name="decision_pair",
        ),
        # Leads with meter_id, so it also serves the foreign key.
        Index("ix_meter_events_meter_effective", meter_id, effective_at, id),
    )


class ReadingRow(Base):
    """A cumulative register reading; values are immutable once stored."""

    __tablename__ = "readings"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    meter_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("meters.id", ondelete="RESTRICT")
    )
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    original_local_date: Mapped[date | None] = mapped_column(Date)
    cumulative_kwh: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    source: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    created_by: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("cumulative_kwh >= 0", name="cumulative_kwh_nonnegative"),
        CheckConstraint(in_values("source", ReadingSource), name="source"),
        CheckConstraint(in_values("status", ReadingStatus), name="status"),
        Index(
            "uq_readings_meter_instant_active",
            meter_id,
            recorded_at,
            unique=True,
            postgresql_where=status != ReadingStatus.VOIDED.value,
        ),
        # Leads with meter_id, so it also serves the foreign key.
        Index("ix_readings_meter_recorded", meter_id, recorded_at, id),
    )
