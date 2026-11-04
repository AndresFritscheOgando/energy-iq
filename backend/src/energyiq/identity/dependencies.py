"""The signed in user for a request (spec 0009/0002 AC-3).

The dependency runs its own short transaction (session lookup and idle
touch), commits it, and returns a frozen value, never an ORM object. The
route then opens its own ``with session.begin():``.
"""

from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request

from energyiq.identity.sessions import (
    find_active_session,
    session_token,
    touch_if_stale,
)
from energyiq.platform.db import DbSession
from energyiq.platform.http.dependencies import AppSettings, Now
from energyiq.platform.http.problems import ProblemError


@dataclass(frozen=True)
class CurrentUser:
    id: UUID
    email: str


def get_current_user(
    request: Request, session: DbSession, settings: AppSettings, now: Now
) -> CurrentUser:
    """401 ``not_authenticated`` unless the cookie names a valid session."""
    token = session_token(request, settings)
    if token is None:
        raise ProblemError(401, "not_authenticated")
    with session.begin():
        active = find_active_session(session, token, now)
        if active is None:
            raise ProblemError(401, "not_authenticated")
        touch_if_stale(session, active, now)
    return CurrentUser(id=active.user_id, email=active.email)


CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]
