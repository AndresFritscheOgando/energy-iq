"""Keyset pagination for every list route (spec 0009 umbrella pagination rules).

Query ``limit`` (1 to 500, default 100) and ``cursor``; response
``{"items": [...], "next_cursor": string | null}``. The cursor is unpadded
base64url of compact JSON ``{"k": [<sort key text>, <id>]}``, where the sort
key text is ``format_utc`` of the timestamp, so it keeps microseconds and
round trips exactly. A cursor only means "rows after this key"; it is not
bound to the filters it was issued with.
"""

import base64
import binascii
import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, cast
from uuid import UUID

from fastapi import Depends, Query
from pydantic import AfterValidator, BaseModel, ConfigDict
from pydantic_core import PydanticCustomError
from sqlalchemy import Select, tuple_
from sqlalchemy.orm import QueryableAttribute, Session

from energyiq.platform.http.formats import format_utc

DEFAULT_LIMIT = 100
MAX_LIMIT = 500
MAX_CURSOR_LENGTH = 256

_BASE64URL = re.compile(r"[A-Za-z0-9_-]+", re.ASCII)
_UTC_TEXT = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{6})?Z", re.ASCII
)


@dataclass(frozen=True)
class CursorKey:
    """The sort key of the last row a page returned."""

    at: datetime
    id: UUID


def encode_cursor(at: datetime, row_id: UUID) -> str:
    payload = json.dumps(
        {"k": [format_utc(at.astimezone(UTC)), str(row_id)]}, separators=(",", ":")
    )
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


def _invalid() -> PydanticCustomError:
    return PydanticCustomError("invalid_cursor", "Cursor is invalid.")


def decode_cursor(value: str) -> CursorKey:
    """Parse a cursor; anything malformed raises ``invalid_cursor``."""
    if len(value) > MAX_CURSOR_LENGTH or not _BASE64URL.fullmatch(value):
        raise _invalid()
    if len(value) % 4 == 1:
        raise _invalid()
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        payload: object = json.loads(raw)
    except (binascii.Error, ValueError):
        raise _invalid() from None
    if not isinstance(payload, dict):
        raise _invalid()
    fields = cast("dict[str, object]", payload)
    key = fields.get("k")
    if set(fields) != {"k"} or not isinstance(key, list):
        raise _invalid()
    parts = cast("list[object]", key)
    if len(parts) != 2:
        raise _invalid()
    at_text, id_text = parts
    if not isinstance(at_text, str) or not isinstance(id_text, str):
        raise _invalid()
    if not _UTC_TEXT.fullmatch(at_text):
        raise _invalid()
    try:
        at = datetime.fromisoformat(at_text)
        row_id = UUID(id_text)
    except ValueError:
        raise _invalid() from None
    if format_utc(at) != at_text:
        raise _invalid()
    return CursorKey(at=at, id=row_id)


def _check_cursor(value: str | None) -> str | None:
    if value is not None:
        decode_cursor(value)
    return value


@dataclass(frozen=True)
class PageParams:
    limit: int
    after: CursorKey | None


def page_params(
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    cursor: Annotated[str | None, Query(), AfterValidator(_check_cursor)] = None,
) -> PageParams:
    """Validated ``limit`` and ``cursor`` (422 ``invalid_cursor`` at
    ``["query", "cursor"]``)."""
    return PageParams(
        limit=limit, after=decode_cursor(cursor) if cursor is not None else None
    )


PageQuery = Annotated[PageParams, Depends(page_params)]


class Page[T](BaseModel):
    """One page of a list; ``next_cursor`` is null on the last page."""

    model_config = ConfigDict(frozen=True)

    items: list[T]
    next_cursor: str | None


def keyset_page[R](
    session: Session,
    statement: Select[R],
    sort_column: QueryableAttribute[datetime],
    id_column: QueryableAttribute[UUID],
    key: Callable[[R], tuple[datetime, UUID]],
    params: PageParams,
) -> tuple[Sequence[R], str | None]:
    """Rows after ``params.after`` in ``(sort, id)`` order, plus the next cursor.

    Fetches one extra row to learn whether another page exists, so the last
    page never carries a cursor.
    """
    if params.after is not None:
        statement = statement.where(
            tuple_(sort_column, id_column) > tuple_(params.after.at, params.after.id)
        )
    statement = statement.order_by(sort_column, id_column).limit(params.limit + 1)
    rows = session.scalars(statement).all()
    if len(rows) <= params.limit:
        return rows, None
    kept = rows[: params.limit]
    at, row_id = key(kept[-1])
    return kept, encode_cursor(at, row_id)
