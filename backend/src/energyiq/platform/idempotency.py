"""Transactional retry keys for authenticated POST routes (spec 0009/0003)."""

import hashlib
import json
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, Request
from pydantic import BaseModel
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    SmallInteger,
    Text,
    Uuid,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Mapped, Session, mapped_column
from starlette.responses import Response

from energyiq.platform.db import Base
from energyiq.platform.http.problems import ProblemError


class IdempotencyKeyRow(Base):
    __tablename__ = "idempotency_keys"

    user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True
    )
    key: Mapped[str] = mapped_column(Text, primary_key=True)
    operation: Mapped[str] = mapped_column(Text)
    request_hash: Mapped[bytes] = mapped_column(LargeBinary(32))
    response_status: Mapped[int | None] = mapped_column(SmallInteger)
    response_body: Mapped[bytes | None] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("char_length(key) BETWEEN 1 AND 255", name="key_length"),
        CheckConstraint("octet_length(request_hash) = 32", name="request_hash_length"),
        CheckConstraint(
            "(response_status IS NULL) = (response_body IS NULL)", name="response_pair"
        ),
        Index("ix_idempotency_keys_expires_at", expires_at),
    )


def idempotent(
    key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> str | None:
    """Validate the optional retry header before authentication and writes."""
    if key is not None and (
        not 1 <= len(key) <= 255 or any(ord(c) < 33 or ord(c) > 126 for c in key)
    ):
        raise ProblemError(400, "invalid_idempotency_key")
    return key


IdempotencyKey = Annotated[str | None, Depends(idempotent)]


def _operation(request: Request) -> str:
    route = request.scope["route"]
    path = str(route.path)
    values = " ".join(str(value) for value in request.path_params.values())
    return f"{request.method} {path}" + (f" {values}" if values else "")


def _body_hash(body: BaseModel | None) -> bytes:
    data = (
        json.dumps(
            body.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        ).encode()
        if body is not None
        else b""
    )
    return hashlib.sha256(data).digest()


def _json_response(result: BaseModel, status: int) -> Response:
    data = json.dumps(
        result.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":")
    ).encode()
    return Response(data, status_code=status, media_type="application/json")


def execute_idempotent[T: BaseModel](
    session: Session,
    user_id: UUID,
    request: Request,
    key: str | None,
    body: BaseModel | None,
    now: datetime,
    status: int,
    action: Callable[[], T],
    *,
    digest: bytes | None = None,
) -> Response:
    """Own or replay a key in the same transaction as the mutation and audit.

    ``digest`` replaces the JSON body hash for routes whose input is not JSON
    (a multipart upload hashes its meter ID and the file's SHA-256).
    """
    operation = _operation(request)
    digest = digest if digest is not None else _body_hash(body)
    with session.begin():
        if key is not None:
            values = {
                "user_id": user_id,
                "key": key,
                "operation": operation,
                "request_hash": digest,
                "response_status": None,
                "response_body": None,
                "created_at": now,
                "expires_at": now + timedelta(hours=24),
            }
            statement = insert(IdempotencyKeyRow).values(**values)
            statement = statement.on_conflict_do_update(
                index_elements=[IdempotencyKeyRow.user_id, IdempotencyKeyRow.key],
                set_={
                    name: getattr(statement.excluded, name)
                    for name in values
                    if name not in {"user_id", "key"}
                },
                where=IdempotencyKeyRow.expires_at <= now,
            ).returning(IdempotencyKeyRow.user_id)
            owned = session.scalar(statement)
            if owned is None:
                row = session.scalar(
                    select(IdempotencyKeyRow).where(
                        IdempotencyKeyRow.user_id == user_id,
                        IdempotencyKeyRow.key == key,
                    )
                )
                if (
                    row is None
                    or row.operation != operation
                    or row.request_hash != digest
                ):
                    raise ProblemError(409, "idempotency_key_reused")
                if row.response_body is None or row.response_status is None:
                    raise RuntimeError("committed idempotency row lacks a response")
                return Response(
                    row.response_body,
                    status_code=row.response_status,
                    media_type="application/json",
                    headers={"Idempotent-Replayed": "true"},
                )
        result = _json_response(action(), status)
        if key is not None:
            session.execute(
                update(IdempotencyKeyRow)
                .where(
                    IdempotencyKeyRow.user_id == user_id, IdempotencyKeyRow.key == key
                )
                .values(response_status=status, response_body=bytes(result.body))
            )
    return result
