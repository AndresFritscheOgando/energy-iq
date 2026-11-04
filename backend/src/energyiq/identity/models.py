"""ORM rows for identity tables (spec 0009/0001 and 0009/0002 data models)."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    LargeBinary,
    Text,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from energyiq.platform.db import Base, in_values


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


class SessionRow(Base):
    """A server side session; the cookie holds the token, this row its hash."""

    __tablename__ = "sessions"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("octet_length(token_hash) = 32", name="token_hash_length"),
    )


class AttemptKind(StrEnum):
    LOGIN = "login"
    REGISTER = "register"


class AuthAttemptRow(Base):
    """One login or register attempt, keyed by HMACs, never raw email or IP."""

    __tablename__ = "auth_attempts"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    kind: Mapped[str] = mapped_column(Text)
    email_key: Mapped[bytes | None] = mapped_column(LargeBinary)
    client_key: Mapped[bytes] = mapped_column(LargeBinary)
    succeeded: Mapped[bool] = mapped_column(Boolean)
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(in_values("kind", AttemptKind), name="kind"),
        Index("ix_auth_attempts_email_key", email_key, attempted_at),
        Index("ix_auth_attempts_client_key", client_key, attempted_at),
    )
