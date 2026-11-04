"""Property and meter routes (spec 0009/0002 AC-7 to AC-10).

Each write opens one ``with session.begin():`` that holds the write and its
audit row. A unique violation aborts the transaction, so it is mapped by
constraint name after the rollback and never logged as text.
"""

from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.exc import IntegrityError
from starlette.responses import Response

from energyiq.identity.dependencies import CurrentUserDep
from energyiq.platform.audit import changed_fields, record_audit
from energyiq.platform.db import DbSession, integrity_problem
from energyiq.platform.http.csrf import require_csrf
from energyiq.platform.http.dependencies import Now, require_json
from energyiq.platform.http.formats import format_instant
from energyiq.platform.http.problems import (
    Problem,
    ProblemError,
    problem_responses,
    request_id_from,
)
from energyiq.platform.pagination import Page, PageQuery
from energyiq.properties import repository
from energyiq.properties.models import Distributor, MeterRow, PropertyRow
from energyiq.properties.schemas import (
    MeterCreate,
    MeterOut,
    MeterPatch,
    PropertyCreate,
    PropertyOut,
    PropertyPatch,
)

router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_csrf)])

CONFLICTS = {
    "uq_properties_owner_nickname_active": (409, "property_name_taken"),
    "uq_meters_property_label_active": (409, "meter_label_taken"),
}

_READ = problem_responses(Problem, (401, 404, 422, 503))
_LIST_OWN = problem_responses(Problem, (401, 422, 503))
_CREATE_OWN = problem_responses(Problem, (400, 401, 403, 409, 413, 415, 422, 503))
_WRITE = problem_responses(Problem, (400, 401, 403, 404, 409, 413, 415, 422, 503))
_ARCHIVE = problem_responses(Problem, (401, 403, 404, 422, 503))
_ACTION = problem_responses(Problem, (401, 403, 404, 409, 422, 503))


def _not_found() -> ProblemError:
    return ProblemError(404, "not_found")


def property_out(row: PropertyRow) -> PropertyOut:
    return PropertyOut(
        id=row.id,
        nickname=row.nickname,
        region=row.region,
        timezone=row.timezone,
        created_at=format_instant(row.created_at),
        updated_at=format_instant(row.updated_at),
    )


def meter_out(row: MeterRow) -> MeterOut:
    return MeterOut(
        id=row.id,
        property_id=row.property_id,
        distributor=Distributor(row.distributor),
        label=row.label,
        register_digits=row.register_digits,
        active=row.active,
        deactivated_at=(
            format_instant(row.deactivated_at) if row.deactivated_at else None
        ),
        created_at=format_instant(row.created_at),
        updated_at=format_instant(row.updated_at),
    )


# Properties -------------------------------------------------------------------


@router.post(
    "/properties",
    status_code=201,
    tags=["properties"],
    dependencies=[Depends(require_json)],
    responses=_CREATE_OWN,
)
def create_property(
    user: CurrentUserDep,
    body: PropertyCreate,
    request: Request,
    session: DbSession,
    now: Now,
) -> PropertyOut:
    row = PropertyRow(
        id=uuid4(),
        owner_user_id=user.id,
        nickname=body.nickname,
        region=body.region,
        timezone=body.timezone,
        created_at=now,
        updated_at=now,
    )
    try:
        with session.begin():
            session.add(row)
            session.flush()
            record_audit(
                session,
                user.id,
                "property.create",
                "property",
                row.id,
                request_id_from(request.scope),
                changed_fields(body.model_fields_set),
                occurred_at=now,
            )
    except IntegrityError as exc:
        raise integrity_problem(exc, CONFLICTS) from None
    return property_out(row)


@router.get("/properties", tags=["properties"], responses=_LIST_OWN)
def list_properties(
    user: CurrentUserDep, page: PageQuery, session: DbSession
) -> Page[PropertyOut]:
    with session.begin():
        rows, next_cursor = repository.list_properties(session, user.id, page)
        items = [property_out(row) for row in rows]
    return Page[PropertyOut](items=items, next_cursor=next_cursor)


@router.get("/properties/{property_id}", tags=["properties"], responses=_READ)
def get_property(
    user: CurrentUserDep, property_id: UUID, session: DbSession
) -> PropertyOut:
    with session.begin():
        row = repository.get_property(session, user.id, property_id)
        if row is None:
            raise _not_found()
    return property_out(row)


@router.patch(
    "/properties/{property_id}",
    tags=["properties"],
    dependencies=[Depends(require_json)],
    responses=_WRITE,
)
def update_property(
    user: CurrentUserDep,
    property_id: UUID,
    body: PropertyPatch,
    request: Request,
    session: DbSession,
    now: Now,
) -> PropertyOut:
    """Change any of nickname, region (null clears it), and timezone.

    Changing the timezone never alters stored readings.
    """
    fields = body.model_fields_set
    values = {**body.model_dump(include=fields), "updated_at": now}
    try:
        with session.begin():
            row = repository.update_property(session, user.id, property_id, values)
            if row is None:
                raise _not_found()
            record_audit(
                session,
                user.id,
                "property.update",
                "property",
                row.id,
                request_id_from(request.scope),
                changed_fields(fields),
                occurred_at=now,
            )
    except IntegrityError as exc:
        raise integrity_problem(exc, CONFLICTS) from None
    return property_out(row)


@router.delete(
    "/properties/{property_id}",
    status_code=204,
    response_class=Response,
    tags=["properties"],
    responses=_ARCHIVE,
)
def archive_property(
    user: CurrentUserDep,
    property_id: UUID,
    request: Request,
    session: DbSession,
    now: Now,
) -> Response:
    """Soft delete: the property, its meters, and their data become 404."""
    with session.begin():
        row = repository.update_property(
            session, user.id, property_id, {"archived_at": now, "updated_at": now}
        )
        if row is None:
            raise _not_found()
        record_audit(
            session,
            user.id,
            "property.archive",
            "property",
            row.id,
            request_id_from(request.scope),
            changed_fields(["archived_at"]),
            occurred_at=now,
        )
    return Response(status_code=204)


# Meters -----------------------------------------------------------------------


@router.post(
    "/properties/{property_id}/meters",
    status_code=201,
    tags=["meters"],
    dependencies=[Depends(require_json)],
    responses=_WRITE,
)
def create_meter(
    user: CurrentUserDep,
    property_id: UUID,
    body: MeterCreate,
    request: Request,
    session: DbSession,
    now: Now,
) -> MeterOut:
    try:
        with session.begin():
            if repository.get_property(session, user.id, property_id) is None:
                raise _not_found()
            row = MeterRow(
                id=uuid4(),
                property_id=property_id,
                distributor=body.distributor.value,
                label=body.label,
                register_digits=body.register_digits,
                active=True,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            session.flush()
            record_audit(
                session,
                user.id,
                "meter.create",
                "meter",
                row.id,
                request_id_from(request.scope),
                changed_fields(body.model_fields_set),
                occurred_at=now,
            )
    except IntegrityError as exc:
        raise integrity_problem(exc, CONFLICTS) from None
    return meter_out(row)


@router.get("/properties/{property_id}/meters", tags=["meters"], responses=_READ)
def list_meters(
    user: CurrentUserDep,
    property_id: UUID,
    page: PageQuery,
    session: DbSession,
    include_inactive: Annotated[bool, Query()] = False,
) -> Page[MeterOut]:
    with session.begin():
        if repository.get_property(session, user.id, property_id) is None:
            raise _not_found()
        rows, next_cursor = repository.list_meters(
            session,
            user.id,
            property_id,
            include_inactive=include_inactive,
            params=page,
        )
        items = [meter_out(row) for row in rows]
    return Page[MeterOut](items=items, next_cursor=next_cursor)


@router.get("/meters/{meter_id}", tags=["meters"], responses=_READ)
def get_meter(user: CurrentUserDep, meter_id: UUID, session: DbSession) -> MeterOut:
    with session.begin():
        row = repository.get_meter(session, user.id, meter_id)
        if row is None:
            raise _not_found()
    return meter_out(row)


@router.patch(
    "/meters/{meter_id}",
    tags=["meters"],
    dependencies=[Depends(require_json)],
    responses=_WRITE,
)
def update_meter(
    user: CurrentUserDep,
    meter_id: UUID,
    body: MeterPatch,
    request: Request,
    session: DbSession,
    now: Now,
) -> MeterOut:
    """Change the label and/or register digits of an active meter."""
    fields = body.model_fields_set
    try:
        with session.begin():
            row = repository.lock_meter(session, user.id, meter_id)
            if row is None:
                raise _not_found()
            if not row.active:
                raise ProblemError(409, "meter_inactive")
            if "label" in fields and body.label is not None:
                row.label = body.label
            if "register_digits" in fields:
                row.register_digits = body.register_digits
            row.updated_at = now
            session.flush()
            record_audit(
                session,
                user.id,
                "meter.update",
                "meter",
                row.id,
                request_id_from(request.scope),
                changed_fields(fields),
                occurred_at=now,
            )
    except IntegrityError as exc:
        raise integrity_problem(exc, CONFLICTS) from None
    return meter_out(row)


@router.post("/meters/{meter_id}/deactivate", tags=["meters"], responses=_ACTION)
def deactivate_meter(
    user: CurrentUserDep,
    meter_id: UUID,
    request: Request,
    session: DbSession,
    now: Now,
) -> MeterOut:
    """Terminal: a replacement physical meter gets a new meter (ADR-006)."""
    with session.begin():
        row = repository.lock_meter(session, user.id, meter_id)
        if row is None:
            raise _not_found()
        if not row.active:
            raise ProblemError(409, "meter_inactive")
        row.active = False
        row.deactivated_at = now
        row.updated_at = now
        session.flush()
        record_audit(
            session,
            user.id,
            "meter.deactivate",
            "meter",
            row.id,
            request_id_from(request.scope),
            changed_fields(["active", "deactivated_at"]),
            occurred_at=now,
        )
    return meter_out(row)
