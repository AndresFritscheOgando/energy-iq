"""Response contract for the reconciliation route."""

from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from energyiq.readings.api.schemas import GapOut

NotItemized = Literal["taxes", "fees", "arrears", "other_charges"]


class _Out(BaseModel):
    model_config = ConfigDict(frozen=True)


class BillWindowOut(_Out):
    """The inclusive local dates and the half open UTC window they map to."""

    local_start: date
    local_end: date
    timezone: str
    utc_start: str
    utc_end: str


class InvoiceFiguresOut(_Out):
    """Invoice values as confirmed. None of these is computed by this route."""

    distributor: str | None
    tariff_class: str | None
    billed_kwh: str | None
    total_dop: str | None
    stated_energy_charge_dop: str | None
    not_itemized: list[NotItemized]


class CoverageOut(_Out):
    complete: bool
    coverage_ratio: str | None
    gaps: list[GapOut]


class ComparisonOut(_Out):
    status: Literal["compared", "not_comparable"]
    billed_kwh: str
    measured_kwh: str | None
    difference_kwh: str | None
    conclusion: Literal["match", "mismatch"] | None
    reasons: list[str]


class RuleCitationOut(_Out):
    resolution_id: str
    source_url: str
    source_digest: str
    effective_start: date
    effective_end: date
    checked_on: date


class EstimateOut(_Out):
    status: Literal["estimated", "abstained"]
    reason: str | None
    energy_charge_dop: str | None
    fixed_charge_dop: str | None
    rule: RuleCitationOut | None


class ReconciliationOut(_Out):
    meter_id: UUID
    invoice_id: UUID
    revision_id: UUID
    window: BillWindowOut
    invoice: InvoiceFiguresOut
    coverage: CoverageOut
    comparison: ComparisonOut
    estimate: EstimateOut
