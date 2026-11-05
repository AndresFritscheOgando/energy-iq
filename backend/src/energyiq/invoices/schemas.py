"""Strict JSON contracts for manual invoice review."""

from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator
from pydantic_core import PydanticCustomError

from energyiq.properties.models import Distributor

Kwh = Annotated[str, StringConstraints(pattern=r"^[0-9]{1,12}(\.[0-9]{1,6})?$")]
Money = Annotated[str, StringConstraints(pattern=r"^[0-9]{1,14}(\.[0-9]{1,2})?$")]
FIELDS = (
    "distributor",
    "period_start",
    "period_end",
    "billed_kwh",
    "total_dop",
    "energy_charge_dop",
    "issue_date",
    "due_date",
)


class DraftFields(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    distributor: Distributor | None = None
    period_start: date | None = None
    period_end: date | None = None
    billed_kwh: Kwh | None = None
    total_dop: Money | None = None
    energy_charge_dop: Money | None = None
    issue_date: date | None = None
    due_date: date | None = None

    @model_validator(mode="after")
    def period_order(self) -> "DraftFields":
        if (
            self.period_start
            and self.period_end
            and self.period_start > self.period_end
        ):
            raise PydanticCustomError(
                "period_order", "Period start cannot be after period end."
            )
        return self


class DraftCreate(DraftFields):
    field_origins: dict[str, Literal["manual"]] = {}

    @model_validator(mode="after")
    def origins_match(self) -> "DraftCreate":
        if any(name not in FIELDS for name in self.field_origins):
            raise PydanticCustomError(
                "invalid_origin", "Field origin names must match invoice fields."
            )
        return self


class CorrectionCreate(DraftFields):
    base_revision_id: UUID
    expected_current_revision_id: UUID | None
    field_origins: dict[str, Literal["manual"]] = {}

    @model_validator(mode="after")
    def changed(self) -> "CorrectionCreate":
        if not self.model_fields_set.intersection(FIELDS):
            raise PydanticCustomError(
                "empty_correction", "Change at least one invoice field."
            )
        if any(
            name not in self.model_fields_set.intersection(FIELDS)
            for name in self.field_origins
        ):
            raise PydanticCustomError(
                "invalid_origin", "Origins must name changed fields."
            )
        return self


class ConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    draft_revision_id: UUID
    expected_current_revision_id: UUID | None


class RevisionOut(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: UUID
    revision_number: int
    status: Literal["draft", "confirmed"]
    actor_id: UUID
    created_at: str
    confirmed_at: str | None
    distributor: Distributor | None
    period_start: date | None
    period_end: date | None
    billed_kwh: str | None
    total_dop: str | None
    energy_charge_dop: str | None
    issue_date: date | None
    due_date: date | None
    field_origins: dict[str, str]
    previous_revision_id: UUID | None
    changed_fields: list[str]
    old_values: dict[str, str | None]


class InvoiceOut(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: UUID
    meter_id: UUID
    created_at: str
    current_revision_id: UUID | None
    revisions: list[RevisionOut]
