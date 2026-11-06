"""Versioned proposal contract (spec 0012/0004 AC-1, AC-2).

The model fills this shape. ``extra="forbid"`` means a key the model invents
(an owner id, a storage path, a tool name) fails validation instead of being
ignored, so model text cannot carry policy. Money and kWh stay strings so no
binary float touches a financial value.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_REVISION = "p1"
PROMPT_REVISION = "pr1"

FieldName = Literal[
    "distributor",
    "tariff_class",
    "period_start",
    "period_end",
    "billed_kwh",
    "total_dop",
    "energy_charge_dop",
    "issue_date",
    "due_date",
]
FIELD_NAMES: tuple[FieldName, ...] = (
    "distributor",
    "tariff_class",
    "period_start",
    "period_end",
    "billed_kwh",
    "total_dop",
    "energy_charge_dop",
    "issue_date",
    "due_date",
)
FieldState = Literal["explicit", "inferred", "not_found"]

Short = Annotated[str, Field(max_length=64)]
Quote = Annotated[str, Field(max_length=300)]
Reason = Annotated[str, Field(max_length=200)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Evidence(_Strict):
    """Where a value was read: a page and a character range of its text.

    ``start`` and ``end`` count Python code points of the normalized page text.
    A UTF-16 consumer (the browser) must convert them for characters outside the
    basic plane. A model may leave them null; code then finds a unique quote.
    """

    quote: Quote | None = None
    page_number: Annotated[int, Field(ge=1, le=1000)] | None = None
    start: Annotated[int, Field(ge=0)] | None = None
    end: Annotated[int, Field(ge=0)] | None = None


class FieldProposal(Evidence):
    state: FieldState = "not_found"
    value: Short | None = None
    uncertainty: Reason | None = None


class Candidate(Evidence):
    value: Short


class Contradiction(_Strict):
    """Two or more readings of one field. The model never picks between them."""

    field: FieldName
    candidates: Annotated[list[Candidate], Field(min_length=2, max_length=5)]


class Proposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fields: dict[FieldName, FieldProposal]
    contradictions: Annotated[list[Contradiction], Field(max_length=20)] = []

    @model_validator(mode="after")
    def fill_missing(self) -> "Proposal":
        # A field the model left out is "not found", never a silent default.
        for name in FIELD_NAMES:
            if name not in self.fields:
                self.fields[name] = FieldProposal()
        return self
