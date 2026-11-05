"""Queries always join an invoice to its owned, unarchived meter."""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from energyiq.invoices.models import InvoiceRevisionRow, InvoiceRow
from energyiq.platform.pagination import PageParams, keyset_page
from energyiq.properties.models import MeterRow, PropertyRow


def owned_invoices(owner_id: UUID) -> Select[InvoiceRow]:
    return (
        select(InvoiceRow)
        .join(MeterRow, MeterRow.id == InvoiceRow.meter_id)
        .join(PropertyRow, PropertyRow.id == MeterRow.property_id)
        .where(
            InvoiceRow.owner_id == owner_id,
            PropertyRow.owner_user_id == owner_id,
            PropertyRow.archived_at.is_(None),
        )
    )


def get_invoice(
    session: Session, owner_id: UUID, invoice_id: UUID, *, lock: bool = False
) -> InvoiceRow | None:
    statement = owned_invoices(owner_id).where(InvoiceRow.id == invoice_id)
    if lock:
        statement = statement.with_for_update(of=InvoiceRow)
    return session.scalars(statement).one_or_none()


def list_invoices(
    session: Session, owner_id: UUID, meter_id: UUID, params: PageParams
) -> tuple[Sequence[InvoiceRow], str | None]:
    return keyset_page(
        session,
        owned_invoices(owner_id).where(InvoiceRow.meter_id == meter_id),
        InvoiceRow.created_at,
        InvoiceRow.id,
        lambda row: (row.created_at, row.id),
        params,
    )


def revisions_by_invoice(
    session: Session, invoice_ids: Sequence[UUID]
) -> dict[UUID, list[InvoiceRevisionRow]]:
    """One query for every invoice on a page, grouped and in revision order."""
    grouped: dict[UUID, list[InvoiceRevisionRow]] = {id_: [] for id_ in invoice_ids}
    if invoice_ids:
        for row in session.scalars(
            select(InvoiceRevisionRow)
            .where(InvoiceRevisionRow.invoice_id.in_(invoice_ids))
            .order_by(InvoiceRevisionRow.invoice_id, InvoiceRevisionRow.revision_number)
        ):
            grouped[row.invoice_id].append(row)
    return grouped


def revisions(session: Session, invoice_id: UUID) -> list[InvoiceRevisionRow]:
    return revisions_by_invoice(session, [invoice_id])[invoice_id]
