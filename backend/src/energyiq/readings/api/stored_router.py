"""Owner scoped stored readings, events, and consumption."""

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.exc import IntegrityError
from starlette.responses import Response

from energyiq.identity.dependencies import CurrentUserDep
from energyiq.platform.audit import record_audit
from energyiq.platform.db import DbSession, constraint_name, integrity_problem
from energyiq.platform.http.csrf import require_csrf
from energyiq.platform.http.dependencies import Now, require_json
from energyiq.platform.http.formats import format_instant
from energyiq.platform.http.problems import (
    Problem,
    ProblemError,
    problem_responses,
    request_id_from,
)
from energyiq.platform.http.types import UtcInstant
from energyiq.platform.idempotency import IdempotencyKey, execute_idempotent, idempotent
from energyiq.platform.pagination import Page, PageQuery
from energyiq.properties import repository as properties
from energyiq.readings import (
    compute_intervals,
    normalize_intervals,
    order_readings,
    summarize_consumption,
)
from energyiq.readings.api.mapping import to_response
from energyiq.readings.api.schemas import ConsumptionSummaryResponse
from energyiq.readings.api.stored_schemas import (
    EventCreate,
    EventOut,
    ReadingCreate,
    ReadingOut,
    ReadingPatch,
)
from energyiq.readings.models import (
    MeterEvent,
    MeterEventType,
    Reading,
    ReadingSource,
    ReadingStatus,
)
from energyiq.readings.persistence import repository
from energyiq.readings.persistence.rows import (
    MeterEventRow,
    MeterEventStatus,
    ReadingRow,
)

router = APIRouter(
    prefix="/api/v1/meters/{meter_id}", dependencies=[Depends(require_csrf)]
)
_READ = problem_responses(Problem, (401, 404, 422, 503))
_WRITE = problem_responses(Problem, (400, 401, 403, 404, 409, 413, 415, 422, 503))
_ACTION = problem_responses(Problem, (400, 401, 403, 404, 409, 422, 503))


def _not_found() -> ProblemError:
    return ProblemError(404, "not_found")


def _validation(field: str, code: str, message: str) -> ProblemError:
    return ProblemError(
        422,
        "validation_error",
        {
            "errors": [
                {
                    "loc": ["query" if field in {"from", "to"} else "body", field],
                    "code": code,
                    "message": message,
                }
            ],
            "errors_truncated": False,
        },
    )


def _future(field: str) -> ProblemError:
    return _validation(field, "reading_in_future", "Value cannot be in the future.")


def reading_out(row: ReadingRow) -> ReadingOut:
    return ReadingOut(
        id=row.id,
        meter_id=row.meter_id,
        recorded_at=format_instant(row.recorded_at),
        original_local_date=row.original_local_date,
        cumulative_kwh=f"{row.cumulative_kwh:.6f}",
        source=ReadingSource(row.source),
        status=ReadingStatus(row.status),
        created_at=format_instant(row.created_at),
        status_changed_at=format_instant(row.status_changed_at)
        if row.status_changed_at
        else None,
    )


def event_out(row: MeterEventRow) -> EventOut:
    return EventOut(
        id=row.id,
        meter_id=row.meter_id,
        event_type=MeterEventType(row.event_type),
        effective_at=format_instant(row.effective_at),
        status=MeterEventStatus(row.status),
        note=row.note,
        created_by=row.created_by,
        created_at=format_instant(row.created_at),
        decided_by=row.decided_by,
        decided_at=format_instant(row.decided_at) if row.decided_at else None,
    )


def _meter(
    session: DbSession, owner_id: UUID, meter_id: UUID, *, active: bool = False
) -> None:
    row = properties.lock_meter(session, owner_id, meter_id)
    if row is None:
        raise _not_found()
    if active and not row.active:
        raise ProblemError(409, "meter_inactive")


def _read_meter(session: DbSession, owner_id: UUID, meter_id: UUID) -> None:
    if properties.get_meter(session, owner_id, meter_id) is None:
        raise _not_found()


@router.post(
    "/readings",
    status_code=201,
    response_model=ReadingOut,
    dependencies=[Depends(require_json), Depends(idempotent)],
    responses=_WRITE,
)
def create_reading(
    meter_id: UUID,
    user: CurrentUserDep,
    body: ReadingCreate,
    request: Request,
    session: DbSession,
    now: Now,
    key: IdempotencyKey,
) -> Response:
    def write() -> ReadingOut:
        _meter(session, user.id, meter_id, active=True)
        timezone = repository.property_timezone(session, user.id, meter_id)
        if timezone is None:
            raise _not_found()
        local_date: date | None = body.local_date
        if local_date is not None:
            if local_date > now.astimezone(ZoneInfo(timezone)).date():
                raise _future("local_date")
            at = datetime.combine(local_date, time(12), ZoneInfo(timezone)).astimezone(
                UTC
            )
        else:
            assert body.recorded_at is not None
            at = body.recorded_at
            if at > now + timedelta(minutes=5):
                raise _future("recorded_at")
        existing = repository.active_at(session, user.id, meter_id, at)
        if existing is not None:
            raise ProblemError(
                409,
                "reading_exists_at_instant",
                {"existing_reading_id": str(existing.id)},
            )
        row = ReadingRow(
            id=uuid4(),
            meter_id=meter_id,
            recorded_at=at,
            original_local_date=local_date,
            cumulative_kwh=Decimal(body.cumulative_kwh),
            source=body.source.value,
            status=body.status.value,
            created_by=user.id,
            created_at=now,
            status_changed_at=None,
        )
        session.add(row)
        session.flush()
        record_audit(
            session,
            user.id,
            "reading.create",
            "reading",
            row.id,
            request_id_from(request.scope),
            {"fields": sorted(body.model_fields_set)},
            occurred_at=now,
        )
        return reading_out(row)

    try:
        return execute_idempotent(session, user.id, request, key, body, now, 201, write)
    except IntegrityError as exc:
        if constraint_name(exc) != "uq_readings_meter_instant_active":
            raise integrity_problem(exc, {}) from None
        at = body.recorded_at
        if at is None and body.local_date is not None:
            with session.begin():
                timezone = repository.property_timezone(session, user.id, meter_id)
                if timezone is None:
                    raise _not_found()
                at = datetime.combine(
                    body.local_date, time(12), ZoneInfo(timezone)
                ).astimezone(UTC)
        assert at is not None
        with session.begin():
            existing = repository.active_at(session, user.id, meter_id, at)
        if existing is None:
            raise RuntimeError(
                "active instant index conflict without reading"
            ) from None
        raise ProblemError(
            409, "reading_exists_at_instant", {"existing_reading_id": str(existing.id)}
        ) from None


@router.get("/readings", responses=_READ)
def list_readings(
    meter_id: UUID,
    user: CurrentUserDep,
    session: DbSession,
    page: PageQuery,
    start: Annotated[UtcInstant | None, Query(alias="from")] = None,
    end: Annotated[UtcInstant | None, Query(alias="to")] = None,
    status: Annotated[ReadingStatus | None, Query()] = None,
    order: Annotated[Literal["asc", "desc"], Query()] = "asc",
) -> Page[ReadingOut]:
    if start is not None and end is not None and start >= end:
        raise _validation("to", "range_order", "to must be after from.")
    with session.begin():
        _read_meter(session, user.id, meter_id)
        rows, cursor = repository.list_readings(
            session,
            user.id,
            meter_id,
            page,
            start,
            end,
            status.value if status else None,
            descending=order == "desc",
        )
        items = [reading_out(row) for row in rows]
    return Page[ReadingOut](items=items, next_cursor=cursor)


@router.patch(
    "/readings/{reading_id}", dependencies=[Depends(require_json)], responses=_WRITE
)
def change_reading_status(
    meter_id: UUID,
    reading_id: UUID,
    user: CurrentUserDep,
    body: ReadingPatch,
    request: Request,
    session: DbSession,
    now: Now,
) -> ReadingOut:
    with session.begin():
        _meter(session, user.id, meter_id)
        row = repository.get_reading(session, user.id, meter_id, reading_id)
        if row is None:
            raise _not_found()
        if row.status != body.status.value:
            if row.status == "voided":
                raise ProblemError(409, "reading_voided")
            old = row.status
            row.status = body.status.value
            row.status_changed_at = now
            session.flush()
            record_audit(
                session,
                user.id,
                "reading.status_change",
                "reading",
                row.id,
                request_id_from(request.scope),
                {"from": old, "to": row.status},
                occurred_at=now,
            )
        result = reading_out(row)
    return result


@router.post(
    "/events",
    status_code=201,
    response_model=EventOut,
    dependencies=[Depends(require_json), Depends(idempotent)],
    responses=_WRITE,
)
def create_event(
    meter_id: UUID,
    user: CurrentUserDep,
    body: EventCreate,
    request: Request,
    session: DbSession,
    now: Now,
    key: IdempotencyKey,
) -> Response:
    def write() -> EventOut:
        _meter(session, user.id, meter_id, active=True)
        if body.effective_at > now + timedelta(minutes=5):
            raise _future("effective_at")
        row = MeterEventRow(
            id=uuid4(),
            meter_id=meter_id,
            event_type=body.event_type.value,
            effective_at=body.effective_at,
            status="pending",
            note=body.note,
            created_by=user.id,
            created_at=now,
            decided_by=None,
            decided_at=None,
        )
        session.add(row)
        session.flush()
        record_audit(
            session,
            user.id,
            "event.create",
            "meter_event",
            row.id,
            request_id_from(request.scope),
            {"fields": sorted(body.model_fields_set)},
            occurred_at=now,
        )
        return event_out(row)

    return execute_idempotent(session, user.id, request, key, body, now, 201, write)


@router.get("/events", responses=_READ)
def list_events(
    meter_id: UUID,
    user: CurrentUserDep,
    session: DbSession,
    page: PageQuery,
    status: Annotated[MeterEventStatus | None, Query()] = None,
) -> Page[EventOut]:
    with session.begin():
        _read_meter(session, user.id, meter_id)
        rows, cursor = repository.list_events(
            session, user.id, meter_id, page, status.value if status else None
        )
        items = [event_out(row) for row in rows]
    return Page[EventOut](items=items, next_cursor=cursor)


def _decide(
    meter_id: UUID,
    event_id: UUID,
    decision: MeterEventStatus,
    user: CurrentUserDep,
    request: Request,
    session: DbSession,
    now: Now,
    key: str | None,
) -> Response:
    def write() -> EventOut:
        _meter(session, user.id, meter_id)
        row = repository.get_event(session, user.id, meter_id, event_id)
        if row is None:
            raise _not_found()
        if row.status != "pending":
            raise ProblemError(409, "event_not_pending")
        row.status = decision.value
        row.decided_by = user.id
        row.decided_at = now
        session.flush()
        action = (
            "event.approve" if decision is MeterEventStatus.APPROVED else "event.reject"
        )
        record_audit(
            session,
            user.id,
            action,
            "meter_event",
            row.id,
            request_id_from(request.scope),
            {"from": "pending", "to": decision.value},
            occurred_at=now,
        )
        return event_out(row)

    return execute_idempotent(session, user.id, request, key, None, now, 200, write)


@router.post(
    "/events/{event_id}/approve",
    response_model=EventOut,
    dependencies=[Depends(idempotent)],
    responses=_ACTION,
)
def approve_event(
    meter_id: UUID,
    event_id: UUID,
    user: CurrentUserDep,
    request: Request,
    session: DbSession,
    now: Now,
    key: IdempotencyKey,
) -> Response:
    return _decide(
        meter_id, event_id, MeterEventStatus.APPROVED, user, request, session, now, key
    )


@router.post(
    "/events/{event_id}/reject",
    response_model=EventOut,
    dependencies=[Depends(idempotent)],
    responses=_ACTION,
)
def reject_event(
    meter_id: UUID,
    event_id: UUID,
    user: CurrentUserDep,
    request: Request,
    session: DbSession,
    now: Now,
    key: IdempotencyKey,
) -> Response:
    return _decide(
        meter_id, event_id, MeterEventStatus.REJECTED, user, request, session, now, key
    )


@router.get("/consumption", responses=_READ)
def stored_consumption(
    meter_id: UUID,
    user: CurrentUserDep,
    session: DbSession,
    start: Annotated[UtcInstant, Query(alias="from")],
    end: Annotated[UtcInstant, Query(alias="to")],
) -> ConsumptionSummaryResponse:
    if end <= start:
        raise _validation("to", "range_order", "to must be after from.")
    if end - start > timedelta(days=366):
        raise _validation("to", "window_too_long", "The window cannot exceed 366 days.")
    with session.begin():
        if properties.share_meter_and_property(session, user.id, meter_id) is None:
            raise _not_found()
        rows, event_rows = repository.consumption_chain(
            session, user.id, meter_id, start, end
        )
        readings = [
            Reading(
                id=row.id,
                meter_id=row.meter_id,
                recorded_at=row.recorded_at.astimezone(UTC),
                cumulative_kwh=row.cumulative_kwh,
                source=ReadingSource(row.source),
                status=ReadingStatus(row.status),
                created_at=row.created_at.astimezone(UTC),
                original_local_date=row.original_local_date,
            )
            for row in rows
        ]
        events = [
            MeterEvent(
                id=row.id,
                meter_id=row.meter_id,
                event_type=MeterEventType(row.event_type),
                effective_at=row.effective_at.astimezone(UTC),
                created_at=row.created_at.astimezone(UTC),
                note=row.note,
                approved_by=row.decided_by if row.status == "approved" else None,
                approved_at=row.decided_at.astimezone(UTC)
                if row.status == "approved" and row.decided_at
                else None,
            )
            for row in event_rows
        ]
    ordered = order_readings(readings)
    if ordered.conflicts:
        raise RuntimeError("stored non voided readings share an instant")
    intervals = compute_intervals(ordered, events)
    summary = summarize_consumption(intervals, meter_id, start, end)
    overlapping = [
        item
        for item in normalize_intervals(intervals)
        if item.interval.start < end and item.interval.end > start
    ]
    return to_response(summary, overlapping)
