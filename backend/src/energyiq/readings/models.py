"""Pure domain records for cumulative readings and meter events."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from energyiq.observations import validate_utc_timestamp

_MAX_READING = Decimal("999999999999.999999")
_MAX_FRACTIONAL_PLACES = 6


class ReadingSource(StrEnum):
    MANUAL = "manual"
    IMPORT = "import"


class ReadingStatus(StrEnum):
    VALID = "valid"
    FLAGGED = "flagged"
    VOIDED = "voided"


class MeterEventType(StrEnum):
    INSTALLED = "installed"
    RESET = "reset"
    REPLACED = "replaced"
    ROLLOVER = "rollover"
    CALIBRATION = "calibration"


def validate_uuid(value: UUID, label: str) -> None:
    if not isinstance(value, UUID):
        raise TypeError(f"{label} must be a UUID")


def _validate_enum(value: StrEnum, expected: type[StrEnum], label: str) -> None:
    if not isinstance(value, expected):
        raise TypeError(f"{label} must be a {expected.__name__}")


def _validate_optional_text(value: str | None, label: str) -> None:
    if value is None:
        return
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string")
    if not value.strip():
        raise ValueError(f"{label} cannot be blank")


def _validate_kwh(value: Decimal) -> None:
    if not isinstance(value, Decimal):
        raise TypeError("cumulative_kwh must be a Decimal")
    if not value.is_finite():
        raise ValueError("cumulative_kwh must be finite")
    if value < 0:
        raise ValueError("cumulative_kwh cannot be negative")
    if value > _MAX_READING:
        raise ValueError("cumulative_kwh exceeds the supported maximum")

    exponent = value.as_tuple().exponent
    if not isinstance(exponent, int):
        raise TypeError("cumulative_kwh must have a numeric exponent")
    extra_places = max(0, -exponent - _MAX_FRACTIONAL_PLACES)
    if extra_places and any(
        digit != 0 for digit in value.as_tuple().digits[-extra_places:]
    ):
        raise ValueError("cumulative_kwh has more than six fractional places")


@dataclass(frozen=True, slots=True)
class Reading:
    """One cumulative kWh observation at an explicit UTC instant."""

    id: UUID
    meter_id: UUID
    recorded_at: datetime
    cumulative_kwh: Decimal
    source: ReadingSource
    status: ReadingStatus
    created_at: datetime
    original_local_date: date | None = None
    note: str | None = None
    source_ref: str | None = None

    def __post_init__(self) -> None:
        validate_uuid(self.id, "id")
        validate_uuid(self.meter_id, "meter_id")
        validate_utc_timestamp(self.recorded_at, "recorded_at")
        _validate_kwh(self.cumulative_kwh)
        _validate_enum(self.source, ReadingSource, "source")
        _validate_enum(self.status, ReadingStatus, "status")
        validate_utc_timestamp(self.created_at, "created_at")
        if self.original_local_date is not None and (
            not isinstance(self.original_local_date, date)
            or isinstance(self.original_local_date, datetime)
        ):
            raise TypeError("original_local_date must be a date")
        _validate_optional_text(self.note, "note")
        _validate_optional_text(self.source_ref, "source_ref")


@dataclass(frozen=True, slots=True)
class MeterEvent:
    """A recorded meter lifecycle event, separate from consumption intervals."""

    id: UUID
    meter_id: UUID
    event_type: MeterEventType
    effective_at: datetime
    created_at: datetime
    note: str | None = None
    approved_by: UUID | None = None
    approved_at: datetime | None = None

    def __post_init__(self) -> None:
        validate_uuid(self.id, "id")
        validate_uuid(self.meter_id, "meter_id")
        _validate_enum(self.event_type, MeterEventType, "event_type")
        validate_utc_timestamp(self.effective_at, "effective_at")
        validate_utc_timestamp(self.created_at, "created_at")
        _validate_optional_text(self.note, "note")
        if (self.approved_by is None) != (self.approved_at is None):
            raise ValueError("approved_by and approved_at must be provided together")
        if self.approved_by is not None:
            validate_uuid(self.approved_by, "approved_by")
        if self.approved_at is not None:
            validate_utc_timestamp(self.approved_at, "approved_at")
