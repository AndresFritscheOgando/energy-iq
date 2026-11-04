"""Audit trail rows (spec 0009/0001 data model).

``record_audit`` arrives with the first audited write (child 0002). The app
role may only insert and select here: audit rows are append only by
privilege.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, ForeignKey, Identity, Index, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
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
