"""Private PDF upload, status, download, retry, and delete (spec 0012/0002).

Every lookup filters on the signed in owner, so a foreign ID is a 404 and the
response never names a storage key. Writes need the CSRF header and accept an
``Idempotency-Key``. The worker, not these routes, moves a run out of
``queued``.
"""

import hashlib
import re
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Request
from sqlalchemy import update
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from starlette.responses import FileResponse, Response

from energyiq.documents import repository
from energyiq.documents.models import ExtractionRunRow, SourceDocumentRow
from energyiq.documents.schemas import (
    CandidateOut,
    ProposalConflictOut,
    ContradictionOut,
    DocumentOut,
    ExtractionOut,
    ProposalOut,
    ProposedFieldOut,
    RunOut,
)
from energyiq.documents.storage import DocumentStore, LocalDocumentStore
from energyiq.documents.upload import receive_pdf
from energyiq.identity.dependencies import CurrentUser, CurrentUserDep
from energyiq.platform.audit import record_audit
from energyiq.platform.db import DbSession
from energyiq.platform.http.csrf import require_csrf
from energyiq.platform.http.dependencies import AppSettings, Now
from energyiq.platform.http.formats import format_instant
from energyiq.platform.http.problems import (
    Problem,
    ProblemError,
    problem_responses,
    request_id_from,
)
from energyiq.platform.idempotency import IdempotencyKey, execute_idempotent, idempotent
from energyiq.platform.pagination import Page
from energyiq.properties import repository as properties

UPLOAD_PATH = re.compile(r"/api/v1/meters/[^/]+/documents")

router = APIRouter(
    prefix="/api/v1", tags=["documents"], dependencies=[Depends(require_csrf)]
)
_READ = problem_responses(Problem, (401, 404, 422, 503))
_WRITE = problem_responses(Problem, (400, 401, 403, 404, 409, 413, 415, 422, 429, 503))


def get_document_store(settings: AppSettings) -> DocumentStore:
    """The private store under ``ENERGYIQ_DOCUMENT_ROOT``; tests override it."""
    return LocalDocumentStore(settings.document_root)


StoreDep = Annotated[DocumentStore, Depends(get_document_store)]


def _missing() -> ProblemError:
    return ProblemError(404, "not_found")


def _instant(value: datetime | None) -> str | None:
    return format_instant(value) if value is not None else None


def _run_out(run: ExtractionRunRow) -> RunOut:
    return RunOut(
        id=run.id,
        run_number=run.run_number,
        state=run.state,  # pyright: ignore[reportArgumentType]
        attempts=run.attempts,
        error_code=run.error_code,
        created_at=format_instant(run.created_at),
        started_at=_instant(run.started_at),
        finished_at=_instant(run.finished_at),
    )


def _document_out(
    document: SourceDocumentRow, run: ExtractionRunRow | None
) -> DocumentOut:
    return DocumentOut(
        id=document.id,
        meter_id=document.meter_id,
        state=repository.document_state(document, run),  # pyright: ignore[reportArgumentType]
        reason_code=run.error_code
        if run is not None and run.state == "failed"
        else None,
        size_bytes=document.size_bytes,
        sha256=document.sha256.hex(),
        created_at=format_instant(document.created_at),
        deleted_at=_instant(document.deleted_at),
        run=_run_out(run) if run is not None else None,
    )


def _owned(
    session: Session, user: CurrentUser, document_id: UUID, *, lock: bool = False
) -> SourceDocumentRow:
    document = repository.get_document(session, user.id, document_id, lock=lock)
    if document is None:
        raise _missing()
    return document


def _new_run(document_id: UUID, number: int, now: datetime) -> ExtractionRunRow:
    return ExtractionRunRow(
        id=uuid4(),
        document_id=document_id,
        run_number=number,
        state="queued",
        attempts=0,
        created_at=now,
    )


def _audit(
    session: Session,
    user: CurrentUser,
    request: Request,
    action: str,
    document_id: UUID,
    now: datetime,
) -> None:
    record_audit(
        session,
        user.id,
        action,  # pyright: ignore[reportArgumentType]
        "document",
        document_id,
        request_id_from(request.scope),
        occurred_at=now,
    )


def _upload_digest(meter_id: UUID, sha256: bytes) -> bytes:
    """Replay hash: meter, file digest, and operation, never file contents."""
    return hashlib.sha256(
        b"upload\0" + str(meter_id).encode() + b"\0" + sha256
    ).digest()


@router.post(
    "/meters/{meter_id}/documents",
    status_code=201,
    response_model=DocumentOut,
    dependencies=[Depends(idempotent)],
    responses=_WRITE,
)
async def upload_document(
    meter_id: UUID,
    user: CurrentUserDep,
    request: Request,
    session: DbSession,
    settings: AppSettings,
    store: StoreDep,
    now: Now,
    key: IdempotencyKey,
) -> Response:
    def check_meter() -> None:
        # Only ownership is answered before the body streams. The limit and
        # inactive meter checks stay inside ``write``: answering them earlier
        # would turn an idempotent replay into a fresh 429 or 409.
        with session.begin():
            if properties.get_meter(session, user.id, meter_id) is None:
                raise _missing()

    await run_in_threadpool(check_meter)
    received = await receive_pdf(request, store, settings.upload_max_bytes)
    storage_key = uuid4()
    stored = False

    def write() -> DocumentOut:
        nonlocal stored
        meter = properties.lock_meter(session, user.id, meter_id)
        if meter is None:
            raise _missing()
        if not meter.active:
            raise ProblemError(409, "meter_inactive")
        repository.lock_owner_documents(session, user.id)
        if (
            repository.count_active_documents(session, user.id)
            >= settings.owner_max_active_docs
        ):
            raise ProblemError(429, "too_many_active")
        document = SourceDocumentRow(
            id=uuid4(),
            owner_id=user.id,
            property_id=meter.property_id,
            meter_id=meter_id,
            storage_key=storage_key,
            sha256=received.sha256,
            mime_type="application/pdf",
            size_bytes=received.size,
            created_at=now,
        )
        session.add(document)
        session.flush()
        run = _new_run(document.id, 1, now)
        session.add(run)
        session.flush()
        # Rename last: a committed row then always has its file, and a crash
        # before the commit leaves an orphan file the reconciler can find.
        store.commit(received.temp, storage_key)
        stored = True
        _audit(session, user, request, "document.upload", document.id, now)
        return _document_out(document, run)

    def run() -> Response:
        return execute_idempotent(
            session,
            user.id,
            request,
            key,
            None,
            now,
            201,
            write,
            digest=_upload_digest(meter_id, received.sha256),
        )

    def row_exists() -> bool:
        try:
            with session.begin():
                return repository.storage_key_exists(session, storage_key)
        except Exception:  # noqa: BLE001 - unsure means keep the file
            return True

    try:
        return await run_in_threadpool(run)
    except BaseException:
        # A cancelled request may have committed before it noticed. Delete the
        # file only when no row names it; otherwise leave it to reconcile.
        if stored and not await run_in_threadpool(row_exists):
            store.delete(storage_key)
        raise
    finally:
        store.discard(received.temp)


@router.get("/documents/{document_id}", response_model=DocumentOut, responses=_READ)
def get_document(
    document_id: UUID, user: CurrentUserDep, session: DbSession
) -> DocumentOut:
    with session.begin():
        document = _owned(session, user, document_id)
        return _document_out(document, repository.latest_run(session, document.id))


def _proposal_out(proposal: dict[str, Any]) -> ProposalOut:
    """Map the stored, already validated proposal; spans and offsets stay private."""
    return ProposalOut(
        fields=[
            ProposedFieldOut(
                name=name,
                state=item["state"],
                value=item["value"],
                quote=item["quote"],
                page_number=item["page_number"],
                uncertainty=item["uncertainty"],
                issues=item["issues"],
                evidence_verified=item["evidence_verified"],
            )
            for name, item in proposal["fields"].items()
        ],
        contradictions=[
            ContradictionOut(
                field=entry["field"],
                candidates=[
                    CandidateOut(
                        value=c["value"],
                        raw_value=c["raw_value"],
                        quote=c["quote"],
                        page_number=c["page_number"],
                        evidence_verified=c["evidence_verified"],
                        issues=c["issues"],
                    )
                    for c in entry["candidates"]
                ],
            )
            for entry in proposal["contradictions"]
        ],
        conflicts=[ProposalConflictOut(**entry) for entry in proposal["conflicts"]],
        requires_review=True,
    )


@router.get(
    "/documents/{document_id}/extractions",
    response_model=Page[ExtractionOut],
    responses=_READ,
)
def list_extractions(
    document_id: UUID, user: CurrentUserDep, session: DbSession
) -> Page[ExtractionOut]:
    """Proposals of this document, newest run first.

    A document holds at most ``doc_max_runs`` runs, so one page is the whole
    list and ``next_cursor`` is always null. A run that failed, or whose model
    output was unusable, has no proposal and is not listed.
    """
    with session.begin():
        document = _owned(session, user, document_id)
        if document.deleted_at is not None:
            raise _missing()
        items = [
            ExtractionOut(
                run_id=run.id,
                run_number=run.run_number,
                model=run.model,
                prompt_version=run.prompt_version,
                finished_at=_instant(run.finished_at),
                proposal=_proposal_out(proposal),
            )
            for run, proposal in repository.extractions(session, document.id)
        ]
    return Page[ExtractionOut](items=items, next_cursor=None)


def _lease_lapsed(run: ExtractionRunRow, now: datetime) -> bool:
    return run.lease_expires_at is None or run.lease_expires_at <= now


@router.get(
    "/documents/{document_id}/source",
    response_class=FileResponse,
    responses={
        200: {"content": {"application/pdf": {}}, "description": "The original PDF"},
        **_READ,
    },
)
def download_source(
    document_id: UUID, user: CurrentUserDep, session: DbSession, store: StoreDep
) -> Response:
    with session.begin():
        document = _owned(session, user, document_id)
        if document.deleted_at is not None:
            raise _missing()
        storage_key = document.storage_key
    try:
        # One read, not exists then open: a purge between the two would be a 500.
        data = store.read(storage_key)
    except FileNotFoundError:
        raise _missing() from None
    return Response(
        data,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="bill-{document_id}.pdf"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox",
        },
    )


@router.post(
    "/documents/{document_id}/retry",
    status_code=201,
    response_model=DocumentOut,
    dependencies=[Depends(idempotent)],
    responses=_WRITE,
)
def retry_document(
    document_id: UUID,
    user: CurrentUserDep,
    request: Request,
    session: DbSession,
    settings: AppSettings,
    now: Now,
    key: IdempotencyKey,
) -> Response:
    def write() -> DocumentOut:
        _owned(session, user, document_id)
        repository.lock_owner_documents(session, user.id)
        document = _owned(session, user, document_id, lock=True)
        if document.deleted_at is not None:
            raise ProblemError(409, "document_deleted")
        runs = repository.lock_runs(session, document.id)
        newest = runs[0] if runs else None
        meter = properties.get_meter(session, user.id, document.meter_id)
        if meter is None or not meter.active:
            raise ProblemError(409, "meter_inactive")
        if newest is not None and newest.state in ("queued", "running"):
            raise ProblemError(409, "run_active")
        if newest is not None and newest.state != "failed":
            raise ProblemError(409, "run_not_failed")
        if len(runs) >= settings.doc_max_runs:
            raise ProblemError(409, "retries_exhausted")
        if (
            repository.count_active_documents(session, user.id)
            >= settings.owner_max_active_docs
        ):
            raise ProblemError(429, "too_many_active")
        run = _new_run(document.id, len(runs) + 1, now)
        session.add(run)
        session.flush()
        _audit(session, user, request, "document.retry", document.id, now)
        return _document_out(document, run)

    return execute_idempotent(session, user.id, request, key, None, now, 201, write)


@router.delete(
    "/documents/{document_id}",
    response_model=DocumentOut,
    dependencies=[Depends(idempotent)],
    responses=_WRITE,
)
def delete_document(
    document_id: UUID,
    user: CurrentUserDep,
    request: Request,
    session: DbSession,
    store: StoreDep,
    now: Now,
    key: IdempotencyKey,
) -> Response:
    storage_key: UUID | None = None

    def write() -> DocumentOut:
        nonlocal storage_key
        _owned(session, user, document_id)
        document = _owned(session, user, document_id, lock=True)
        runs = repository.lock_runs(session, document.id)
        newest = runs[0] if runs else None
        if document.deleted_at is not None:
            storage_key = document.storage_key if document.purged_at is None else None
            return _document_out(document, newest)
        # A running run whose lease lapsed has no live worker; it must not hold
        # the owner's bill hostage. The compare and set finish keeps a late
        # worker from overwriting what we write here.
        if any(run.state == "running" and not _lease_lapsed(run, now) for run in runs):
            raise ProblemError(409, "run_active")
        if repository.is_source_of_revision(session, document.id):
            raise ProblemError(409, "document_in_use")
        document.deleted_at = now
        for run in runs:
            run.output = None
            if run.state == "queued" or (
                run.state == "running" and _lease_lapsed(run, now)
            ):
                run.state = "failed"
                run.lease_owner = None
                run.lease_expires_at = None
                run.error_code = "document_deleted"
                run.finished_at = now
        session.flush()
        _audit(session, user, request, "document.delete", document.id, now)
        storage_key = document.storage_key
        return _document_out(document, newest)

    response = execute_idempotent(session, user.id, request, key, None, now, 200, write)
    if storage_key is not None:
        purge_file(session, store, storage_key, now)
    return response


def purge_file(
    session: Session, store: DocumentStore, storage_key: UUID, now: datetime
) -> None:
    """Remove the file of a committed tombstone, then record that it is gone.

    A failure here is not an error for the caller: the tombstone is already
    durable, and the reconciliation command finishes the removal.
    """
    try:
        store.delete(storage_key)
    except OSError:
        return
    with session.begin():
        session.execute(
            update(SourceDocumentRow)
            .where(
                SourceDocumentRow.storage_key == storage_key,
                SourceDocumentRow.deleted_at.is_not(None),
                SourceDocumentRow.purged_at.is_(None),
            )
            .values(purged_at=now)
            .execution_options(synchronize_session=False)
        )
