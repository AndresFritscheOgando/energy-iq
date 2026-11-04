"""Database backed auth rate limits (spec 0009/0002 AC-6).

Login is refused when the email has 5 or more failures in the last 15
minutes since its last success, or the client has 20 or more login attempts
in the last 15 minutes. Register is refused when the client has 5 or more
register attempts in the last hour. Refused requests are not recorded.

Keys are ``HMAC_SHA256(secret_key, value)``, so no raw email or IP address
is stored. Each check runs under ``pg_advisory_xact_lock`` on the first 8
bytes of the email key (login) or client key (register), held until the
attempt row commits, so parallel requests cannot overshoot the email limit.
"""

import hashlib
import hmac
import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import ColumnElement, func, select, text
from sqlalchemy.orm import Session

from energyiq.identity.models import AttemptKind, AuthAttemptRow

LOGIN_WINDOW = timedelta(minutes=15)
LOGIN_EMAIL_FAILURE_LIMIT = 5
LOGIN_CLIENT_LIMIT = 20
REGISTER_WINDOW = timedelta(hours=1)
REGISTER_CLIENT_LIMIT = 5
UNKNOWN_CLIENT = "unknown"


def attempt_key(secret: str, value: str) -> bytes:
    return hmac.new(secret.encode(), value.encode(), hashlib.sha256).digest()


def lock_key(key: bytes) -> int:
    """The first 8 bytes of an HMAC key as a signed bigint."""
    return int.from_bytes(key[:8], "big", signed=True)


def advisory_lock(session: Session, key: bytes) -> None:
    """Serialize checks for ``key`` until the transaction ends."""
    session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key(key)})


def retry_after(
    counted: Sequence[datetime], limit: int, window: timedelta, now: datetime
) -> int | None:
    """Seconds until one counted attempt leaves the window, or ``None`` when
    under the limit. ``t`` is the ``(n - L + 1)``th oldest counted attempt."""
    n = len(counted)
    if n < limit:
        return None
    oldest_that_matters = counted[n - limit]
    seconds = (oldest_that_matters + window - now).total_seconds()
    return max(1, math.ceil(seconds))


@dataclass(frozen=True)
class AttemptKeys:
    email_key: bytes | None
    client_key: bytes


def _times(session: Session, *conditions: ColumnElement[bool]) -> list[datetime]:
    return list(
        session.scalars(
            select(AuthAttemptRow.attempted_at)
            .where(*conditions)
            .order_by(AuthAttemptRow.attempted_at)
        )
    )


def login_retry_after(session: Session, keys: AttemptKeys, now: datetime) -> int | None:
    """``Retry-After`` seconds when a login limit is hit, else ``None``.

    Call after ``advisory_lock`` on the email key.
    """
    assert keys.email_key is not None
    window_start = now - LOGIN_WINDOW
    last_success = session.scalar(
        select(func.max(AuthAttemptRow.attempted_at)).where(
            AuthAttemptRow.kind == AttemptKind.LOGIN,
            AuthAttemptRow.email_key == keys.email_key,
            AuthAttemptRow.succeeded,
        )
    )
    since = max(window_start, last_success) if last_success else window_start
    failures = _times(
        session,
        AuthAttemptRow.kind == AttemptKind.LOGIN,
        AuthAttemptRow.email_key == keys.email_key,
        AuthAttemptRow.succeeded.is_(False),
        AuthAttemptRow.attempted_at > since,
    )
    from_client = _times(
        session,
        AuthAttemptRow.kind == AttemptKind.LOGIN,
        AuthAttemptRow.client_key == keys.client_key,
        AuthAttemptRow.attempted_at > window_start,
    )
    waits = [
        wait
        for wait in (
            retry_after(failures, LOGIN_EMAIL_FAILURE_LIMIT, LOGIN_WINDOW, now),
            retry_after(from_client, LOGIN_CLIENT_LIMIT, LOGIN_WINDOW, now),
        )
        if wait is not None
    ]
    return max(waits) if waits else None


def register_retry_after(
    session: Session, keys: AttemptKeys, now: datetime
) -> int | None:
    """``Retry-After`` seconds when the register limit is hit, else ``None``.

    Call after ``advisory_lock`` on the client key.
    """
    attempts = _times(
        session,
        AuthAttemptRow.kind == AttemptKind.REGISTER,
        AuthAttemptRow.client_key == keys.client_key,
        AuthAttemptRow.attempted_at > now - REGISTER_WINDOW,
    )
    return retry_after(attempts, REGISTER_CLIENT_LIMIT, REGISTER_WINDOW, now)


def record_attempt(
    session: Session,
    kind: AttemptKind,
    keys: AttemptKeys,
    *,
    succeeded: bool,
    now: datetime,
) -> None:
    session.add(
        AuthAttemptRow(
            kind=kind,
            email_key=keys.email_key,
            client_key=keys.client_key,
            succeeded=succeeded,
            attempted_at=now,
        )
    )
