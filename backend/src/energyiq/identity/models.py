"""ORM rows for identity tables (spec 0009/0001 data model)."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from energyiq.platform.db import Base


class UserRow(Base):
    """An account. ``email`` is stored normalized by the app (child 0002)."""

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("char_length(email) <= 254", name="email_length"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    email: Mapped[str] = mapped_column(Text, unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
