"""Manual invoice draft, confirmation, and correction routes."""

from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Literal, cast
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Request
from psycopg.types.range import Range
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.responses import Response

from energyiq.documents import repository as documents
from energyiq.identity.dependencies import CurrentUserDep
from energyiq.invoices import repository
from energyiq.invoices.models import (
    InvoiceCurrentPeriodRow,
    InvoiceRevisionRow,
    InvoiceRow,
)
from energyiq.invoices.schemas import (
    FIELDS,
    ConfirmRequest,
    CorrectionCreate,
    DraftCreate,
    InvoiceOut,
    RevisionOut,
)
from energyiq.platform.audit import record_audit
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
from energyiq.platform.idempotency import IdempotencyKey, execute_idempotent, idempotent
from energyiq.platform.pagination import Page, PageQuery
from energyiq.properties import repository as properties
from energyiq.properties.models import Distributor

router = APIRouter(
    prefix="/api/v1", tags=["invoices"], dependencies=[Depends(require_csrf)]
)
_READ = problem_responses(Problem, (401, 404, 422, 503))
_WRITE = problem_responses(Problem, (400, 401, 403, 404, 409, 413, 415, 422, 503))


def _missing() -> ProblemError:
    return ProblemError(404, "not_found")


def _meter(
    session: Session, owner_id: UUID, meter_id: UUID, *, active: bool = False
) -> str:
    meter = properties.lock_meter(session, owner_id, meter_id)
    if meter is None:
        raise _missing()
    if active and not meter.active:
        raise ProblemError(409, "meter_inactive")
    return meter.distributor


def _locked(session: Session, owner_id: UUID, invoice_id: UUID) -> InvoiceRow:
    row = repository.get_invoice(session, owner_id, invoice_id, lock=True)
    if row is None:  # deleted between the unlocked read and the lock
        raise _missing()
    return row


def _revision_out(row: InvoiceRevisionRow) -> RevisionOut:
    return RevisionOut(
        id=row.id,
        revision_number=row.revision_number,
        status=cast("Literal['draft', 'confirmed']", row.status),
        actor_id=row.actor_id,
        created_at=format_instant(row.created_at),
        confirmed_at=format_instant(row.confirmed_at) if row.confirmed_at else None,
        distributor=Distributor(row.distributor) if row.distributor else None,
        tariff_class=row.tariff_class,
        period_start=row.period_start,
        period_end=row.period_end,
        billed_kwh=f"{row.billed_kwh:.6f}" if row.billed_kwh is not None else None,
        total_dop=f"{row.total_dop:.2f}" if row.total_dop is not None else None,
        energy_charge_dop=f"{row.energy_charge_dop:.2f}"
        if row.energy_charge_dop is not None
        else None,
        issue_date=row.issue_date,
        due_date=row.due_date,
        field_origins=row.field_origins,
        source_document_id=row.source_document_id,
        previous_revision_id=row.previous_revision_id,
        changed_fields=row.changed_fields,
        old_values=row.old_values,
    )


def _invoice_out(row: InvoiceRow, history: Sequence[InvoiceRevisionRow]) -> InvoiceOut:
    return InvoiceOut(
        id=row.id,
        meter_id=row.meter_id,
        created_at=format_instant(row.created_at),
        current_revision_id=row.current_revision_id,
        revisions=[_revision_out(revision) for revision in history],
    )


def _loaded(session: Session, row: InvoiceRow) -> InvoiceOut:
    return _invoice_out(row, repository.revisions(session, row.id))


def _draft_values(body: DraftCreate | CorrectionCreate) -> dict[str, object]:
    result: dict[str, object] = {}
    for name in FIELDS:
        value: object = getattr(body, name)
        if name in {"billed_kwh", "total_dop", "energy_charge_dop"} and isinstance(
            value, str
        ):
            value = Decimal(value)
        if name == "distributor" and isinstance(value, Distributor):
            value = value.value
        result[name] = value
    return result


def _origins(values: dict[str, object], supplied: Mapping[str, str]) -> dict[str, str]:
    return {
        name: supplied.get(name, "manual")
        for name, value in values.items()
        if value is not None
    }


def _same_value(name: str, value: object, proposed: object) -> bool:
    """Does a draft value equal the proposed one, compared as typed values?"""
    if value is None or not isinstance(proposed, str):
        return False
    try:
        if name in {"billed_kwh", "total_dop", "energy_charge_dop"}:
            return isinstance(value, Decimal) and value == Decimal(proposed)
        if name in {"period_start", "period_end", "issue_date", "due_date"}:
            return value == date.fromisoformat(proposed)
    except (ValueError, ArithmeticError):
        return False
    return value == proposed


def _check_source(
    session: Session,
    owner_id: UUID,
    meter_id: UUID,
    body: DraftCreate,
    values: dict[str, object],
) -> None:
    """A linked document is the owner's, on this meter, and not deleted.

    A foreign, wrong meter, or deleted document answers the same 404 as an
    unknown ID. A ``document`` origin must equal the retained proposal, so the
    label cannot claim a source the document does not hold.
    """
    if body.source_document_id is None:
        return
    document = documents.get_document(session, owner_id, body.source_document_id)
    if document is None or document.meter_id != meter_id or document.deleted_at:
        raise _missing()
    claimed = [
        name for name, origin in body.field_origins.items() if origin == "document"
    ]
    if not claimed:
        return
    found = documents.latest_extraction(session, document.id)
    fields: dict[str, Any] = found[1].get("fields", {}) if found is not None else {}
    wrong: list[str] = []
    for name in sorted(claimed):
        item = fields.get(name)
        if not (
            isinstance(item, dict)
            and cast("dict[str, Any]", item).get("state") in {"explicit", "inferred"}
            and _same_value(
                name, values.get(name), cast("dict[str, Any]", item).get("value")
            )
        ):
            wrong.append(name)
    if wrong:
        raise ProblemError(422, "origin_mismatch", {"fields": wrong})


@router.post(
    "/meters/{meter_id}/invoices",
    status_code=201,
    response_model=InvoiceOut,
    dependencies=[Depends(require_json), Depends(idempotent)],
    responses=_WRITE,
)
def create_invoice(
    meter_id: UUID,
    user: CurrentUserDep,
    body: DraftCreate,
    request: Request,
    session: DbSession,
    now: Now,
    key: IdempotencyKey,
) -> Response:
    def write() -> InvoiceOut:
        _meter(session, user.id, meter_id, active=True)
        values = _draft_values(body)
        _check_source(session, user.id, meter_id, body, values)
        row = InvoiceRow(
            id=uuid4(),
            meter_id=meter_id,
            owner_id=user.id,
            current_revision_id=None,
            created_at=now,
        )
        session.add(row)
        session.flush()
        revision = InvoiceRevisionRow(
            id=uuid4(),
            invoice_id=row.id,
            revision_number=1,
            status="draft",
            actor_id=user.id,
            created_at=now,
            confirmed_at=None,
            source_document_id=body.source_document_id,
            field_origins=_origins(values, body.field_origins),
            previous_revision_id=None,
            changed_fields=sorted(name for name in FIELDS if values[name] is not None),
            old_values={},
            **values,
        )
        session.add(revision)
        session.flush()
        record_audit(
            session,
            user.id,
            "invoice.create",
            "invoice",
            row.id,
            request_id_from(request.scope),
            {"fields": sorted(body.model_fields_set)},
            occurred_at=now,
        )
        return _loaded(session, row)

    return execute_idempotent(session, user.id, request, key, body, now, 201, write)


@router.get("/meters/{meter_id}/invoices", responses=_READ)
def list_invoices(
    meter_id: UUID, user: CurrentUserDep, session: DbSession, page: PageQuery
) -> Page[InvoiceOut]:
    with session.begin():
        if properties.get_meter(session, user.id, meter_id) is None:
            raise _missing()
        rows, cursor = repository.list_invoices(session, user.id, meter_id, page)
        history = repository.revisions_by_invoice(session, [row.id for row in rows])
        items = [_invoice_out(row, history[row.id]) for row in rows]
    return Page[InvoiceOut](items=items, next_cursor=cursor)


@router.get("/invoices/{invoice_id}", responses=_READ)
def get_invoice(
    invoice_id: UUID, user: CurrentUserDep, session: DbSession
) -> InvoiceOut:
    with session.begin():
        row = repository.get_invoice(session, user.id, invoice_id)
        if row is None:
            raise _missing()
        result = _loaded(session, row)
    return result


@router.post(
    "/invoices/{invoice_id}/revisions",
    status_code=201,
    response_model=InvoiceOut,
    dependencies=[Depends(require_json), Depends(idempotent)],
    responses=_WRITE,
)
def correct_invoice(
    invoice_id: UUID,
    user: CurrentUserDep,
    body: CorrectionCreate,
    request: Request,
    session: DbSession,
    now: Now,
    key: IdempotencyKey,
) -> Response:
    def write() -> InvoiceOut:
        row = repository.get_invoice(session, user.id, invoice_id)
        if row is None:
            raise _missing()
        _meter(session, user.id, row.meter_id, active=True)
        row = _locked(session, user.id, invoice_id)
        if row.current_revision_id != body.expected_current_revision_id:
            raise ProblemError(409, "stale_invoice_revision")
        prior = repository.revisions(session, row.id)[-1]
        if prior.id != body.base_revision_id:
            raise ProblemError(409, "stale_invoice_revision")
        values = {name: getattr(prior, name) for name in FIELDS}
        changes = _draft_values(body)
        # Compare normalized values, so "100" equals "100.000000" and a repeat is no change.
        changed = sorted(
            name
            for name in body.model_fields_set.intersection(FIELDS)
            if changes[name] != values[name]
        )
        if not changed:
            raise ProblemError(422, "empty_correction")
        old_values = {
            name: str(values[name]) if values[name] is not None else None
            for name in changed
        }
        values.update({name: changes[name] for name in changed})
        start, end = values["period_start"], values["period_end"]
        if isinstance(start, date) and isinstance(end, date) and start > end:
            raise ProblemError(422, "invalid_invoice_period")
        origins = dict(prior.field_origins)
        for name in changed:
            if values[name] is None:
                origins.pop(name, None)
            else:
                origins[name] = body.field_origins.get(name, "manual")
        revision = InvoiceRevisionRow(
            id=uuid4(),
            invoice_id=row.id,
            revision_number=prior.revision_number + 1,
            status="draft",
            actor_id=user.id,
            created_at=now,
            confirmed_at=None,
            source_document_id=prior.source_document_id,
            field_origins=origins,
            previous_revision_id=prior.id,
            changed_fields=changed,
            old_values=old_values,
            **values,
        )
        session.add(revision)
        session.flush()
        record_audit(
            session,
            user.id,
            "invoice.correct",
            "invoice",
            row.id,
            request_id_from(request.scope),
            {"fields": changed},
            occurred_at=now,
        )
        return _loaded(session, row)

    return execute_idempotent(session, user.id, request, key, body, now, 201, write)


@router.post(
    "/invoices/{invoice_id}/confirm",
    response_model=InvoiceOut,
    dependencies=[Depends(require_json), Depends(idempotent)],
    responses=_WRITE,
)
def confirm_invoice(
    invoice_id: UUID,
    user: CurrentUserDep,
    body: ConfirmRequest,
    request: Request,
    session: DbSession,
    now: Now,
    key: IdempotencyKey,
) -> Response:
    def write() -> InvoiceOut:
        row = repository.get_invoice(session, user.id, invoice_id)
        if row is None:
            raise _missing()
        distributor = _meter(session, user.id, row.meter_id, active=True)
        row = _locked(session, user.id, invoice_id)
        if row.current_revision_id != body.expected_current_revision_id:
            raise ProblemError(409, "stale_invoice_revision")
        history = repository.revisions(session, row.id)
        revision = history[-1]
        if revision.id != body.draft_revision_id or revision.status != "draft":
            raise ProblemError(409, "stale_invoice_revision")
        required = (
            "distributor",
            "period_start",
            "period_end",
            "billed_kwh",
            "total_dop",
        )
        missing = [
            name
            for name in required
            if getattr(revision, name) is None or name not in revision.field_origins
        ]
        if missing:
            raise ProblemError(422, "invoice_incomplete", {"fields": missing})
        if revision.distributor != distributor:
            raise ProblemError(409, "distributor_discrepancy")
        if revision.period_start is None or revision.period_end is None:
            raise ProblemError(422, "invoice_incomplete")
        if (
            revision.period_start > revision.period_end
            or revision.period_end == date.max
        ):
            raise ProblemError(422, "invalid_invoice_period")
        revision.status = "confirmed"
        revision.confirmed_at = now
        row.current_revision_id = revision.id
        session.flush()
        period = session.get(InvoiceCurrentPeriodRow, row.id)
        end_exclusive = revision.period_end + timedelta(days=1)
        if period is None:
            period = InvoiceCurrentPeriodRow(
                invoice_id=row.id,
                meter_id=row.meter_id,
                current_revision_id=revision.id,
                local_daterange=Range(revision.period_start, end_exclusive, "[)"),
            )
            session.add(period)
        else:
            period.current_revision_id = revision.id
            period.local_daterange = Range(revision.period_start, end_exclusive, "[)")
        session.flush()
        record_audit(
            session,
            user.id,
            "invoice.confirm",
            "invoice",
            row.id,
            request_id_from(request.scope),
            {"revision_id": str(revision.id), "fields": revision.changed_fields},
            occurred_at=now,
        )
        return _loaded(session, row)

    try:
        return execute_idempotent(session, user.id, request, key, body, now, 200, write)
    except IntegrityError as exc:
        raise integrity_problem(
            exc,
            {
                "ex_invoice_current_periods_meter_overlap": (
                    409,
                    "invoice_period_overlap",
                )
            },
        ) from None
