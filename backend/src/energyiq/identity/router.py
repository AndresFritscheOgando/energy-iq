"""Auth routes: register, login, logout, me (spec 0009/0002 AC-1 to AC-6).

Security records that must survive a failed request (the attempt row and
the failed ``auth.login`` or ``auth.register`` audit row) commit in their own
transaction before the 401 or 409 is raised. Refused (429) requests record
nothing.
"""

from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from starlette.responses import Response

from energyiq.identity.dependencies import CurrentUserDep
from energyiq.identity.models import AttemptKind, UserRow
from energyiq.identity.passwords import PasswordService
from energyiq.identity.rate_limits import (
    UNKNOWN_CLIENT,
    AttemptKeys,
    advisory_lock,
    attempt_key,
    login_retry_after,
    record_attempt,
    register_retry_after,
)
from energyiq.identity.schemas import CredentialsIn, UserOut
from energyiq.identity.sessions import (
    clear_session_cookie,
    create_session,
    find_active_session,
    revoke_session,
    session_token,
    set_session_cookie,
)
from energyiq.platform.audit import record_audit
from energyiq.platform.db import DbSession, constraint_name, integrity_problem
from energyiq.platform.http.csrf import require_csrf
from energyiq.platform.http.dependencies import AppSettings, Now, require_json
from energyiq.platform.http.formats import format_instant
from energyiq.platform.http.problems import (
    Problem,
    ProblemError,
    problem_responses,
    request_id_from,
)
from energyiq.platform.settings import Settings

router = APIRouter(
    prefix="/api/v1/auth", tags=["auth"], dependencies=[Depends(require_csrf)]
)


def get_passwords(request: Request) -> PasswordService:
    passwords: PasswordService = request.app.state.passwords
    return passwords


Passwords = Annotated[PasswordService, Depends(get_passwords)]


def user_out(row: UserRow) -> UserOut:
    return UserOut(
        id=row.id, email=row.email, created_at=format_instant(row.created_at)
    )


def _client_key(request: Request, settings: Settings) -> bytes:
    host = request.client.host if request.client else UNKNOWN_CLIENT
    return attempt_key(settings.secret_key.get_secret_value(), host)


def _too_many(seconds: int) -> ProblemError:
    return ProblemError(429, "too_many_attempts", headers={"Retry-After": str(seconds)})


@router.post(
    "/register",
    status_code=201,
    dependencies=[Depends(require_json)],
    responses=problem_responses(Problem, (400, 403, 409, 413, 415, 422, 429, 503)),
)
def register(
    body: CredentialsIn,
    request: Request,
    response: Response,
    session: DbSession,
    settings: AppSettings,
    now: Now,
    passwords: Passwords,
) -> UserOut:
    """Create an account and sign it in."""
    keys = AttemptKeys(email_key=None, client_key=_client_key(request, settings))
    request_id = request_id_from(request.scope)
    signed_in: tuple[UserOut, str] | None = None
    try:
        with session.begin():
            advisory_lock(session, keys.client_key)
            wait = register_retry_after(session, keys, now)
            if wait is not None:
                raise _too_many(wait)
            existing = session.scalar(
                select(UserRow.id).where(UserRow.email == body.email)
            )
            if existing is None:
                user = UserRow(
                    id=uuid4(),
                    email=body.email,
                    password_hash=passwords.hash(body.password),
                    created_at=now,
                )
                session.add(user)
                session.flush()
                token = create_session(session, user.id, now)
                record_audit(
                    session,
                    user.id,
                    "auth.register",
                    "user",
                    user.id,
                    request_id,
                    occurred_at=now,
                )
                signed_in = (user_out(user), token)
            else:
                record_audit(
                    session,
                    None,
                    "auth.register",
                    "user",
                    existing,
                    request_id,
                    {"outcome": "email_taken"},
                    occurred_at=now,
                )
            record_attempt(
                session, AttemptKind.REGISTER, keys, succeeded=existing is None, now=now
            )
    except IntegrityError as exc:
        if constraint_name(exc) != "uq_users_email":
            raise integrity_problem(exc, {}) from None
        # A parallel register took the email after the existence check.
        with session.begin():
            record_attempt(
                session, AttemptKind.REGISTER, keys, succeeded=False, now=now
            )
            record_audit(
                session,
                None,
                "auth.register",
                "user",
                None,
                request_id,
                {"outcome": "email_taken"},
                occurred_at=now,
            )
        raise ProblemError(409, "email_taken") from None
    if signed_in is None:
        raise ProblemError(409, "email_taken")
    out, token = signed_in
    set_session_cookie(response, settings, token)
    return out


@router.post(
    "/login",
    dependencies=[Depends(require_json)],
    responses=problem_responses(Problem, (400, 401, 403, 413, 415, 422, 429, 503)),
)
def login(
    body: CredentialsIn,
    request: Request,
    response: Response,
    session: DbSession,
    settings: AppSettings,
    now: Now,
    passwords: Passwords,
) -> UserOut:
    """Sign in; unknown email, wrong password, and disabled user look alike."""
    secret = settings.secret_key.get_secret_value()
    email_key = attempt_key(secret, body.email)
    keys = AttemptKeys(email_key=email_key, client_key=_client_key(request, settings))
    request_id = request_id_from(request.scope)
    previous_token = session_token(request, settings)
    signed_in: tuple[UserOut, str] | None = None
    with session.begin():
        advisory_lock(session, email_key)
        wait = login_retry_after(session, keys, now)
        if wait is not None:
            raise _too_many(wait)
        user = session.scalars(
            select(UserRow).where(UserRow.email == body.email)
        ).one_or_none()
        if user is None:
            passwords.verify_dummy(body.password)
            failure: str | None = "unknown_email"
        elif not passwords.verify(user.password_hash, body.password):
            failure = "wrong_password"
        elif user.disabled_at is not None:
            failure = "disabled"
        else:
            failure = None

        if failure is not None:
            record_attempt(session, AttemptKind.LOGIN, keys, succeeded=False, now=now)
            record_audit(
                session,
                None,
                "auth.login_failed",
                "user",
                user.id if user is not None else None,
                request_id,
                {"reason": failure},
                occurred_at=now,
            )
        else:
            assert user is not None
            if passwords.needs_rehash(user.password_hash):
                user.password_hash = passwords.hash(body.password)
            if previous_token is not None:
                # Session fixation defense: a valid cookie sent here is revoked.
                previous = find_active_session(session, previous_token, now)
                if previous is not None:
                    revoke_session(session, previous.session_id, now)
            token = create_session(session, user.id, now)
            record_attempt(session, AttemptKind.LOGIN, keys, succeeded=True, now=now)
            record_audit(
                session,
                user.id,
                "auth.login",
                "user",
                user.id,
                request_id,
                occurred_at=now,
            )
            signed_in = (user_out(user), token)
    if signed_in is None:
        raise ProblemError(401, "invalid_credentials")
    out, token = signed_in
    set_session_cookie(response, settings, token)
    return out


@router.post(
    "/logout",
    status_code=204,
    response_class=Response,
    responses=problem_responses(Problem, (403, 503)),
)
def logout(
    request: Request, session: DbSession, settings: AppSettings, now: Now
) -> Response:
    """Revoke the current session if there is one; 204 either way."""
    token = session_token(request, settings)
    if token is not None:
        with session.begin():
            active = find_active_session(session, token, now)
            if active is not None:
                revoke_session(session, active.session_id, now)
                record_audit(
                    session,
                    active.user_id,
                    "auth.logout",
                    "user",
                    active.user_id,
                    request_id_from(request.scope),
                    occurred_at=now,
                )
    response = Response(status_code=204)
    clear_session_cookie(response, settings)
    return response


@router.get("/me", responses=problem_responses(Problem, (401, 503)))
def me(user: CurrentUserDep, session: DbSession) -> UserOut:
    """The signed in account."""
    with session.begin():
        row = session.get_one(UserRow, user.id)
    return user_out(row)
