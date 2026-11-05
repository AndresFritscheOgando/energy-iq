"""Audit trail rows and ``record_audit`` (spec 0009 umbrella audit rules).

The app role may only insert and select here: audit rows are append only by
privilege. Metadata holds field names and state transitions only, never an
email, password, nickname, note text, token, or IP address.
"""

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, ForeignKey, Identity, Index, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column
from sqlalchemy.sql import text

from energyiq.platform.db import Base


class AuditEventRow(Base):
    """One audited action; ``metadata`` holds field names and transitions only."""

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    actor_user_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    action: Mapped[str] = mapped_column(Text)
    entity_type: Mapped[str] = mapped_column(Text)
    entity_id: Mapped[UUID | None] = mapped_column(Uuid)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    request_id: Mapped[str] = mapped_column(Text)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, server_default=text("'{}'::jsonb")
    )

    __table_args__ = (Index("ix_audit_events_entity", entity_type, entity_id),)


EntityType = Literal[
    "user", "property", "meter", "reading", "meter_event", "invoice", "document"
]

AuditAction = Literal[
    "auth.register",
    "auth.login",
    "auth.login_failed",
    "auth.logout",
    "property.create",
    "property.update",
    "property.archive",
    "meter.create",
    "meter.update",
    "meter.deactivate",
    "reading.create",
    "reading.status_change",
    "event.create",
    "event.approve",
    "event.reject",
    "invoice.create",
    "invoice.correct",
    "invoice.confirm",
    "document.upload",
    "document.retry",
    "document.delete",
]


def record_audit(
    session: Session,
    actor_id: UUID | None,
    action: AuditAction,
    entity_type: EntityType,
    entity_id: UUID | None,
    request_id: str,
    metadata: Mapping[str, Any] | None = None,
    *,
    occurred_at: datetime,
) -> None:
    """Add one audit row to the caller's open transaction."""
    session.add(
        AuditEventRow(
            actor_user_id=actor_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            occurred_at=occurred_at,
            request_id=request_id,
            metadata_=dict(metadata or {}),
        )
    )


def changed_fields(names: Iterable[str]) -> dict[str, list[str]]:
    """Audit metadata naming the changed fields, in a stable order."""
    return {"fields": sorted(names)}
