"""Server side sessions in an HttpOnly cookie (spec 0009/0002 AC-3, AC-4).

The browser holds a random 256 bit token; the database holds only its
SHA-256. A session is valid while it is not revoked, ``now < expires_at``
(login plus 14 days), ``now < last_seen_at + 24h``, and its user is not
disabled. ``last_seen_at`` moves only when it is at least 5 minutes old, so
most requests write nothing.
"""

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.orm import Session
from starlette.requests import Request
from starlette.responses import Response

from energyiq.identity.models import SessionRow, UserRow
from energyiq.platform.settings import Settings

COOKIE_NAME = "energyiq_session"
SECURE_COOKIE_NAME = "__Host-energyiq_session"
ABSOLUTE_LIFETIME = timedelta(days=14)
IDLE_TIMEOUT = timedelta(hours=24)
TOUCH_INTERVAL = timedelta(minutes=5)
TOKEN_BYTES = 32


def cookie_name(settings: Settings) -> str:
    """``__Host-`` whenever the cookie is ``Secure`` (no Domain, Path ``/``)."""
    return SECURE_COOKIE_NAME if settings.session_cookie_secure else COOKIE_NAME


def token_hash(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


def session_token(request: Request, settings: Settings) -> str | None:
    """The raw cookie token, if the request carries one."""
    token = request.cookies.get(cookie_name(settings))
    return token or None


@dataclass(frozen=True)
class ActiveSession:
    """A valid session and its user, as plain values."""

    session_id: UUID
    user_id: UUID
    email: str
    last_seen_at: datetime


def find_active_session(
    session: Session, token: str, now: datetime
) -> ActiveSession | None:
    """The valid session for ``token``, else ``None``; one statement."""
    row = session.execute(
        select(
            SessionRow.id, SessionRow.user_id, UserRow.email, SessionRow.last_seen_at
        )
        .join(UserRow, UserRow.id == SessionRow.user_id)
        .where(
            SessionRow.token_hash == token_hash(token),
            SessionRow.revoked_at.is_(None),
            SessionRow.expires_at > now,
            SessionRow.last_seen_at > now - IDLE_TIMEOUT,
            UserRow.disabled_at.is_(None),
        )
    ).one_or_none()
    if row is None:
        return None
    return ActiveSession(
        session_id=row.id,
        user_id=row.user_id,
        email=row.email,
        last_seen_at=row.last_seen_at,
    )


def touch_if_stale(session: Session, active: ActiveSession, now: datetime) -> None:
    """Move ``last_seen_at`` to ``now`` once it is at least 5 minutes old."""
    if now - active.last_seen_at >= TOUCH_INTERVAL:
        session.execute(
            update(SessionRow)
            .where(SessionRow.id == active.session_id)
            .values(last_seen_at=now)
        )


def create_session(session: Session, user_id: UUID, now: datetime) -> str:
    """Insert a new session and return its raw token (never stored)."""
    token = secrets.token_urlsafe(TOKEN_BYTES)
    session.add(
        SessionRow(
            id=uuid4(),
            user_id=user_id,
            token_hash=token_hash(token),
            created_at=now,
            last_seen_at=now,
            expires_at=now + ABSOLUTE_LIFETIME,
        )
    )
    return token


def revoke_session(session: Session, session_id: UUID, now: datetime) -> None:
    session.execute(
        update(SessionRow)
        .where(SessionRow.id == session_id, SessionRow.revoked_at.is_(None))
        .values(revoked_at=now)
    )


def set_session_cookie(response: Response, settings: Settings, token: str) -> None:
    response.set_cookie(
        cookie_name(settings),
        token,
        max_age=int(ABSOLUTE_LIFETIME.total_seconds()),
        path="/",
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite="lax",
    )


def clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        cookie_name(settings),
        path="/",
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite="lax",
    )
