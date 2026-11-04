"""HTTP contracts for stored readings and meter events."""

from datetime import date
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator, model_validator
from pydantic_core import PydanticCustomError

from energyiq.platform.http.types import KwhString, UtcInstant
from energyiq.readings.models import MeterEventType, ReadingSource, ReadingStatus
from energyiq.readings.persistence.rows import MeterEventStatus

_INPUT = ConfigDict(extra="forbid", frozen=True)


class ReadingCreate(BaseModel):
    model_config = _INPUT
    recorded_at: UtcInstant | None = None
    local_date: date | None = None
    cumulative_kwh: KwhString
    status: ReadingStatus = ReadingStatus.VALID
    source: ReadingSource = ReadingSource.MANUAL

    @model_validator(mode="after")
    def one_time(self) -> Self:
        if (self.recorded_at is None) == (self.local_date is None):
            raise PydanticCustomError(
                "exactly_one_of", "Give exactly one of recorded_at or local_date."
            )
        if self.status is ReadingStatus.VOIDED:
            raise PydanticCustomError(
                "invalid_enum", "Value is not one of the allowed options."
            )
        return self


class ReadingPatch(BaseModel):
    model_config = _INPUT
    status: ReadingStatus


class ReadingOut(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: UUID
    meter_id: UUID
    recorded_at: str
    original_local_date: date | None
    cumulative_kwh: str
    source: ReadingSource
    status: ReadingStatus
    created_at: str
    status_changed_at: str | None


class EventCreate(BaseModel):
    model_config = _INPUT
    event_type: MeterEventType
    effective_at: UtcInstant
    note: str | None = None

    @field_validator("note", mode="before")
    @classmethod
    def trim_note(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        trimmed = value.strip()
        if len(trimmed) > 500:
            raise PydanticCustomError(
                "invalid_text_length", "Text length is out of range."
            )
        return trimmed or None


class EventOut(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: UUID
    meter_id: UUID
    event_type: MeterEventType
    effective_at: str
    status: MeterEventStatus
    note: str | None
    created_by: UUID
    created_at: str
    decided_by: UUID | None
    decided_at: str | None
