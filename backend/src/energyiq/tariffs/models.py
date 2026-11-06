"""Published tariff rows (spec 0012/0006).

The app role can only read these tables. The trusted maintenance command writes
them as the migrator role, and a trigger refuses any later update or delete, so
a published rule is immutable. A replacement is a new version.
"""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import DATERANGE, ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column

from energyiq.platform.db import Base, in_values
from energyiq.tariffs.domain import ChargeType, RoundingMode, RoundingScope


class TariffScheduleRow(Base):
    __tablename__ = "tariff_schedules"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    distributor: Mapped[str] = mapped_column(Text)
    tariff_class: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer)
    effective_start: Mapped[date] = mapped_column(Date)
    effective_end: Mapped[date] = mapped_column(Date)
    effective_daterange: Mapped[object] = mapped_column(
        DATERANGE,
        Computed("daterange(effective_start, effective_end, '[]')", persisted=True),
    )
    resolution_id: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str] = mapped_column(Text)
    source_digest: Mapped[str] = mapped_column(Text)
    published_on: Mapped[date] = mapped_column(Date)
    checked_on: Mapped[date] = mapped_column(Date)
    checked_by: Mapped[str] = mapped_column(Text)
    rounding_places: Mapped[int] = mapped_column(Integer)
    rounding_mode: Mapped[str] = mapped_column(Text)
    rounding_scope: Mapped[str] = mapped_column(Text)
    manifest_revision: Mapped[str] = mapped_column(Text)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint(
            "distributor", "tariff_class", "version", name="uq_tariff_schedules_version"
        ),
        UniqueConstraint(
            "distributor",
            "tariff_class",
            "resolution_id",
            name="uq_tariff_schedules_resolution",
        ),
        ExcludeConstraint(
            ("distributor", "="),
            ("tariff_class", "="),
            ("effective_daterange", "&&"),
            name="ex_tariff_schedules_overlap",
            using="gist",
        ),
        CheckConstraint("effective_end >= effective_start", name="effective_order"),
        CheckConstraint("checked_on >= published_on", name="checked_order"),
        CheckConstraint("source_digest ~ '^[0-9a-f]{64}$'", name="digest_format"),
        CheckConstraint(
            in_values("distributor", ("EDESUR", "EDEESTE", "EDENORTE")),
            name="distributor",
        ),
        CheckConstraint("tariff_class = 'BTS-1'", name="class_supported"),
        CheckConstraint("rounding_places BETWEEN 0 AND 6", name="rounding_places"),
        CheckConstraint(
            in_values("rounding_mode", tuple(mode.value for mode in RoundingMode)),
            name="rounding_mode",
        ),
        CheckConstraint(
            in_values("rounding_scope", tuple(scope.value for scope in RoundingScope)),
            name="rounding_scope",
        ),
    )


class TariffBandRow(Base):
    __tablename__ = "tariff_bands"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    schedule_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "tariff_schedules.id", ondelete="RESTRICT", name="fk_tariff_bands_schedule"
        ),
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer)
    charge_type: Mapped[str] = mapped_column(Text)
    from_kwh: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    to_kwh: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 6))

    __table_args__ = (
        UniqueConstraint("schedule_id", "position", name="uq_tariff_bands_position"),
        CheckConstraint(
            in_values("charge_type", tuple(kind.value for kind in ChargeType)),
            name="charge_type",
        ),
        CheckConstraint("from_kwh >= 0 AND amount >= 0", name="nonnegative"),
        CheckConstraint("to_kwh IS NULL OR to_kwh >= from_kwh", name="range_order"),
    )
