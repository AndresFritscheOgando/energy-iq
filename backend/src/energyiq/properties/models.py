"""ORM rows for properties and meters (spec 0009/0001 data model)."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from energyiq.platform.db import Base, in_values

DEFAULT_TIMEZONE = "America/Santo_Domingo"


class Distributor(StrEnum):
    EDESUR = "EDESUR"
    EDEESTE = "EDEESTE"
    EDENORTE = "EDENORTE"
    OTHER = "OTHER"


class PropertyRow(Base):
    """A household property owned by one user."""

    __tablename__ = "properties"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    owner_user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    nickname: Mapped[str] = mapped_column(Text)
    region: Mapped[str | None] = mapped_column(Text)
    timezone: Mapped[str] = mapped_column(
        Text, server_default=text(f"'{DEFAULT_TIMEZONE}'")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "char_length(nickname) BETWEEN 1 AND 80", name="nickname_length"
        ),
        CheckConstraint("char_length(region) <= 80", name="region_length"),
        CheckConstraint(
            "char_length(timezone) BETWEEN 1 AND 64", name="timezone_length"
        ),
        Index(
            "uq_properties_owner_nickname_active",
            owner_user_id,
            func.lower(nickname),
            unique=True,
            postgresql_where=archived_at.is_(None),
        ),
    )


class MeterRow(Base):
    """A meter at a property; inactive once ``deactivated_at`` is set."""

    __tablename__ = "meters"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    property_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("properties.id", ondelete="RESTRICT"), index=True
    )
    distributor: Mapped[str] = mapped_column(Text)
    label: Mapped[str] = mapped_column(Text)
    register_digits: Mapped[int | None] = mapped_column(SmallInteger)
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(in_values("distributor", Distributor), name="distributor"),
        CheckConstraint("char_length(label) BETWEEN 1 AND 60", name="label_length"),
        CheckConstraint(
            "register_digits BETWEEN 4 AND 9", name="register_digits_range"
        ),
        CheckConstraint("active = (deactivated_at IS NULL)", name="active_deactivated"),
        Index(
            "uq_meters_property_label_active",
            property_id,
            func.lower(label),
            unique=True,
            postgresql_where=active,
        ),
    )
