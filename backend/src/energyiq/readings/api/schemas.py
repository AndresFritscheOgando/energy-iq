"""Request and response models for the consumption summary endpoint.

These are the HTTP contract, separate from the domain dataclasses. Request
models enforce every rule the domain checks, so mapping a validated request
never raises (spec 0008 AC-5).
"""

from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_core import PydanticCustomError

from energyiq.platform.http.problems import Problem
from energyiq.platform.http.types import KwhString, UtcInstant
from energyiq.readings import (
    GapReason,
    IntervalReason,
    IntervalStatus,
    MeterEventType,
    ReadingSource,
    ReadingStatus,
)

MAX_READINGS = 5_000
MAX_EVENTS = 500

_REQUEST_CONFIG = ConfigDict(extra="forbid", frozen=True)
_RESPONSE_CONFIG = ConfigDict(frozen=True)


class WindowIn(BaseModel):
    """Half open ``[start, end)`` window; any explicit offset, stored as UTC."""

    model_config = _REQUEST_CONFIG

    start: UtcInstant
    end: UtcInstant

    @model_validator(mode="after")
    def _end_after_start(self) -> Self:
        if self.end <= self.start:
            raise PydanticCustomError(
                "window_order", "window.end must be after window.start."
            )
        return self


class ReadingIn(BaseModel):
    """One cumulative reading; ``created_at`` is stamped by the server."""

    model_config = _REQUEST_CONFIG

    id: UUID
    recorded_at: UtcInstant
    cumulative_kwh: KwhString
    status: ReadingStatus = ReadingStatus.VALID
    source: ReadingSource = ReadingSource.MANUAL


class EventIn(BaseModel):
    """One meter event; approval fields come together or not at all."""

    model_config = _REQUEST_CONFIG

    id: UUID
    event_type: MeterEventType
    effective_at: UtcInstant
    approved_by: UUID | None = None
    approved_at: UtcInstant | None = None

    @model_validator(mode="after")
    def _approval_pair(self) -> Self:
        if (self.approved_by is None) != (self.approved_at is None):
            raise PydanticCustomError(
                "approval_pair", "approved_by and approved_at must be given together."
            )
        return self


class ConsumptionSummaryRequest(BaseModel):
    """Readings and events for one meter, summarized over one window."""

    model_config = _REQUEST_CONFIG

    meter_id: UUID
    window: WindowIn
    readings: list[ReadingIn] = Field(max_length=MAX_READINGS)
    events: list[EventIn] = Field(default_factory=list[EventIn], max_length=MAX_EVENTS)


class WindowOut(BaseModel):
    model_config = _RESPONSE_CONFIG

    start: str
    end: str


class GapOut(BaseModel):
    """One in window span without a measured value, with its cause."""

    model_config = _RESPONSE_CONFIG

    start: str
    end: str
    duration: str
    reason: GapReason
    interval_reason: IntervalReason | None
    previous_reading_id: UUID | None
    current_reading_id: UUID | None
    event_ids: list[UUID]


class IntervalOut(BaseModel):
    """One interval of the chain; ``measured_in_window`` marks summed ones."""

    model_config = _RESPONSE_CONFIG

    previous_reading_id: UUID
    current_reading_id: UUID
    start: str
    end: str
    duration: str
    status: IntervalStatus
    reason: IntervalReason | None
    event_ids: list[UUID]
    consumption_kwh: str | None
    kwh_per_day: str | None
    measured_in_window: bool


class ConsumptionSummaryResponse(BaseModel):
    """Exact window summary plus every interval; Decimals are strings."""

    model_config = _RESPONSE_CONFIG

    meter_id: UUID
    window: WindowOut
    measured_kwh: str
    covered: str
    uncovered: str
    coverage_ratio: str
    average_kwh_per_day: str | None
    gaps: list[GapOut]
    intervals: list[IntervalOut]


class DuplicateIdOut(BaseModel):
    """An id repeated inside one collection, with every input index."""

    model_config = _RESPONSE_CONFIG

    collection: Literal["readings", "events"]
    id: UUID
    input_indexes: list[int]


class ConflictEntryOut(BaseModel):
    model_config = _RESPONSE_CONFIG

    input_index: int
    reading_id: UUID
    status: ReadingStatus


class ConflictOut(BaseModel):
    """Readings at the same UTC instant (P1-02 conflict group)."""

    model_config = _RESPONSE_CONFIG

    recorded_at: str
    entries: list[ConflictEntryOut]


class ConsumptionProblem(Problem):
    """Problem body for the summary route, with its extension members."""

    duplicates: list[DuplicateIdOut] | None = None
    conflicts: list[ConflictOut] | None = None
