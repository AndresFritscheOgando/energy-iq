"""Owner scoped invoice reconciliation (spec 0012/0006 AC-3 to AC-5)."""

from datetime import date
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from energyiq.identity.dependencies import CurrentUserDep
from energyiq.invoices import repository as invoices
from energyiq.invoices.models import InvoiceRevisionRow
from energyiq.platform.db import DbSession
from energyiq.platform.http.csrf import require_csrf
from energyiq.platform.http.formats import format_decimal, format_utc
from energyiq.platform.http.problems import Problem, ProblemError, problem_responses
from energyiq.readings.api.mapping import gap_out
from energyiq.readings.api.window import load_window
from energyiq.readings.persistence import repository as readings
from energyiq.reconciliation import service
from energyiq.reconciliation.schemas import (
    BillWindowOut,
    ComparisonOut,
    CoverageOut,
    EstimateOut,
    InvoiceFiguresOut,
    NotItemized,
    ReconciliationOut,
    RuleCitationOut,
)
from energyiq.tariffs import repository as tariffs
from energyiq.tariffs.domain import (
    SUPPORTED_CLASS,
    Abstention,
    EnergyEstimate,
    estimate_for_invoice,
)

router = APIRouter(
    prefix="/api/v1/meters/{meter_id}",
    tags=["reconciliation"],
    dependencies=[Depends(require_csrf)],
)
_READ = problem_responses(Problem, (401, 404, 409, 422, 503))
_NOT_ITEMIZED: list[NotItemized] = ["taxes", "fees", "arrears", "other_charges"]


def _money(value: Decimal | None) -> str | None:
    return None if value is None else f"{value:.2f}"


def _published_amount(value: Decimal) -> str:
    """A published DOP amount at two places when exact there, else at full scale."""
    cents = value.quantize(Decimal("0.01"))
    return format_decimal(cents if cents == value else value.normalize())


def _estimate_out(result: EnergyEstimate | Abstention) -> EstimateOut:
    if isinstance(result, Abstention):
        return EstimateOut(
            status="abstained",
            reason=result.reason.value,
            energy_charge_dop=None,
            fixed_charge_dop=None,
            rule=None,
        )
    rule = result.schedule
    return EstimateOut(
        status="estimated",
        reason=None,
        energy_charge_dop=format_decimal(result.energy_charge),
        fixed_charge_dop=_published_amount(result.fixed_charge),
        rule=RuleCitationOut(
            resolution_id=rule.resolution_id,
            source_url=rule.source_url,
            source_digest=rule.source_digest,
            effective_start=rule.effective_start,
            effective_end=rule.effective_end,
            checked_on=rule.checked_on,
        ),
    )


def _confirmed_revision(
    session: Session, owner_id: UUID, meter_id: UUID, invoice_id: UUID
) -> tuple[InvoiceRevisionRow, date, date, Decimal]:
    """The current confirmed revision and its required values.

    An unowned invoice, or one on another meter, is a 404. A draft only is a 409.
    """
    invoice = invoices.get_invoice(session, owner_id, invoice_id)
    if invoice is None or invoice.meter_id != meter_id:
        raise ProblemError(404, "not_found")
    if invoice.current_revision_id is None:
        raise ProblemError(409, "invoice_unconfirmed")
    revision = session.get(InvoiceRevisionRow, invoice.current_revision_id)
    if (
        revision is None
        or revision.status != "confirmed"
        or revision.period_start is None
        or revision.period_end is None
        or revision.billed_kwh is None
    ):
        raise ProblemError(409, "invoice_unconfirmed")
    return revision, revision.period_start, revision.period_end, revision.billed_kwh


@router.get("/reconciliation", responses=_READ, response_model=ReconciliationOut)
def reconcile(
    meter_id: UUID, invoice_id: UUID, user: CurrentUserDep, session: DbSession
) -> ReconciliationOut:
    with session.begin():
        revision, start, end, billed = _confirmed_revision(
            session, user.id, meter_id, invoice_id
        )
        timezone = readings.property_timezone(session, user.id, meter_id)
        if timezone is None:
            raise ProblemError(404, "not_found")
        try:
            utc_start, utc_end = service.bill_window(start, end, timezone)
        except (OverflowError, ValueError):
            raise ProblemError(409, "invoice_period_out_of_range") from None
        if service.period_days(start, end) > service.MAX_WINDOW_DAYS:
            comparison = service.too_long(billed)
            coverage = CoverageOut(complete=False, coverage_ratio=None, gaps=[])
        else:
            loaded = load_window(session, user.id, meter_id, utc_start, utc_end)
            if loaded is None:
                raise ProblemError(404, "not_found")
            summary, _ = loaded
            comparison = service.compare(billed, summary)
            coverage = CoverageOut(
                complete=comparison.conclusion is not None,
                coverage_ratio=format_decimal(summary.coverage_ratio),
                gaps=[gap_out(gap) for gap in summary.gaps],
            )
        schedules = (
            tariffs.schedules_overlapping(
                session, revision.distributor or "", SUPPORTED_CLASS, start, end
            )
            if revision.tariff_class == SUPPORTED_CLASS and revision.distributor
            else []
        )
        estimate = estimate_for_invoice(
            schedules,
            distributor=revision.distributor,
            tariff_class=revision.tariff_class,
            period_start=start,
            period_end=end,
            billed_kwh=billed,
        )
        return ReconciliationOut(
            meter_id=meter_id,
            invoice_id=invoice_id,
            revision_id=revision.id,
            window=BillWindowOut(
                local_start=start,
                local_end=end,
                timezone=timezone,
                utc_start=format_utc(utc_start),
                utc_end=format_utc(utc_end),
            ),
            invoice=InvoiceFiguresOut(
                distributor=revision.distributor,
                tariff_class=revision.tariff_class,
                billed_kwh=format_decimal(billed),
                total_dop=_money(revision.total_dop),
                stated_energy_charge_dop=_money(revision.energy_charge_dop),
                not_itemized=_NOT_ITEMIZED,
            ),
            coverage=coverage,
            comparison=ComparisonOut(
                status="compared" if comparison.conclusion else "not_comparable",
                billed_kwh=format_decimal(comparison.billed_kwh),
                measured_kwh=None
                if comparison.measured_kwh is None
                else format_decimal(comparison.measured_kwh),
                difference_kwh=None
                if comparison.difference_kwh is None
                else format_decimal(comparison.difference_kwh),
                conclusion="match"
                if comparison.conclusion == "match"
                else "mismatch"
                if comparison.conclusion
                else None,
                reasons=[reason.value for reason in comparison.reasons],
            ),
            estimate=_estimate_out(estimate),
        )
