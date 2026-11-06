"""Owner scoped queries for documents and runs.

Every read filters ``owner_id`` in the same statement, so a foreign or missing
ID gives ``None`` and the route answers 404.
"""

from typing import Any, cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from energyiq.documents.models import (
    ACTIVE_RUN_STATES,
    ExtractionRunRow,
    SourceDocumentRow,
)
from energyiq.invoices.models import InvoiceRevisionRow

STATE_BY_RUN = {
    "queued": "uploaded",
    "running": "processing",
    "succeeded": "needs_review",
    "failed": "failed",
}


def document_state(document: SourceDocumentRow, run: ExtractionRunRow | None) -> str:
    """The state a client sees, taken from the deleted marker and latest run."""
    if document.deleted_at is not None:
        return "deleted"
    return STATE_BY_RUN[run.state] if run is not None else "uploaded"


def get_document(
    session: Session, owner_id: UUID, document_id: UUID, *, lock: bool = False
) -> SourceDocumentRow | None:
    statement = select(SourceDocumentRow).where(
        SourceDocumentRow.id == document_id, SourceDocumentRow.owner_id == owner_id
    )
    if lock:
        statement = statement.with_for_update().execution_options(
            populate_existing=True
        )
    return session.scalars(statement).one_or_none()


def latest_run(session: Session, document_id: UUID) -> ExtractionRunRow | None:
    return session.scalars(
        select(ExtractionRunRow)
        .where(ExtractionRunRow.document_id == document_id)
        .order_by(ExtractionRunRow.run_number.desc())
        .limit(1)
        .execution_options(populate_existing=True)
    ).one_or_none()


def extractions(
    session: Session, document_id: UUID
) -> list[tuple[ExtractionRunRow, dict[str, Any]]]:
    """Succeeded runs that hold a validated proposal, newest first."""
    found: list[tuple[ExtractionRunRow, dict[str, Any]]] = []
    for run in session.scalars(
        select(ExtractionRunRow)
        .where(
            ExtractionRunRow.document_id == document_id,
            ExtractionRunRow.state == "succeeded",
        )
        .order_by(ExtractionRunRow.run_number.desc())
        .execution_options(populate_existing=True)
    ):
        extraction: Any = (run.output or {}).get("extraction")
        proposal: Any = (
            cast("dict[str, Any]", extraction).get("proposal")
            if isinstance(extraction, dict)
            else None
        )
        if isinstance(proposal, dict):
            found.append((run, cast("dict[str, Any]", proposal)))
    return found


def latest_extraction(
    session: Session, document_id: UUID
) -> tuple[ExtractionRunRow, dict[str, Any]] | None:
    found = extractions(session, document_id)
    return found[0] if found else None


def lock_runs(session: Session, document_id: UUID) -> list[ExtractionRunRow]:
    """Every run of one document, locked, newest first."""
    return list(
        session.scalars(
            select(ExtractionRunRow)
            .where(ExtractionRunRow.document_id == document_id)
            .order_by(ExtractionRunRow.run_number.desc())
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )


def lock_owner_documents(session: Session, owner_id: UUID) -> None:
    """Serialize document admission for one owner until the transaction ends."""
    session.execute(
        select(func.pg_advisory_xact_lock(func.hashtextextended(str(owner_id), 0)))
    )


def count_active_documents(session: Session, owner_id: UUID) -> int:
    """Documents of one owner that are not deleted and have an active run."""
    return (
        session.scalar(
            select(func.count(SourceDocumentRow.id))
            .join(
                ExtractionRunRow, ExtractionRunRow.document_id == SourceDocumentRow.id
            )
            .where(
                SourceDocumentRow.owner_id == owner_id,
                SourceDocumentRow.deleted_at.is_(None),
                ExtractionRunRow.state.in_(ACTIVE_RUN_STATES),
            )
        )
        or 0
    )


def is_source_of_revision(session: Session, document_id: UUID) -> bool:
    return (
        session.scalar(
            select(InvoiceRevisionRow.id)
            .where(InvoiceRevisionRow.source_document_id == document_id)
            .limit(1)
        )
        is not None
    )


def storage_key_exists(session: Session, storage_key: UUID) -> bool:
    return (
        session.scalar(
            select(func.count())
            .select_from(SourceDocumentRow)
            .where(SourceDocumentRow.storage_key == storage_key)
        )
        == 1
    )
