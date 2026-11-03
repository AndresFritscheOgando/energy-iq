"""Exact interval consumption with explicit meter continuity boundaries."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from itertools import pairwise
from uuid import UUID

from energyiq.consumption import calculate_consumption
from energyiq.observations import validate_utc_timestamp
from energyiq.readings.models import (
    MeterEvent,
    MeterEventType,
    Reading,
    ReadingStatus,
    validate_uuid,
)
from energyiq.readings.ordering import ReadingOrderResult, order_readings


class IntervalStatus(StrEnum):
    VALID = "valid"
    INVALID = "invalid"


class IntervalReason(StrEnum):
    FLAGGED_READING = "flagged_reading"
    UNAPPROVED_EVENT = "unapproved_event"
    METER_BOUNDARY = "meter_boundary"
    UNSUPPORTED_EVENT = "unsupported_event"
    UNEXPLAINED_DECREASE = "unexplained_decrease"


_EVENT_REASONS = frozenset(
    {
        IntervalReason.UNAPPROVED_EVENT,
        IntervalReason.METER_BOUNDARY,
        IntervalReason.UNSUPPORTED_EVENT,
    }
)


@dataclass(frozen=True, slots=True)
class ConsumptionInterval:
    """One measured pair or a pair whose kWh must remain unknown."""

    meter_id: UUID
    previous_reading_id: UUID
    current_reading_id: UUID
    start: datetime
    end: datetime
    status: IntervalStatus
    event_ids: tuple[UUID, ...] = ()
    consumption_kwh: Decimal | None = None
    reason: IntervalReason | None = None

    def __post_init__(self) -> None:
        for label in ("meter_id", "previous_reading_id", "current_reading_id"):
            validate_uuid(getattr(self, label), label)
        validate_utc_timestamp(self.start, "start")
        validate_utc_timestamp(self.end, "end")
        if self.end <= self.start:
            raise ValueError("interval end must be after start")
        if not isinstance(self.status, IntervalStatus):
            raise TypeError("status must be an IntervalStatus")
        if not isinstance(self.event_ids, tuple):
            raise TypeError("event_ids must be a tuple")
        for index, event_id in enumerate(self.event_ids):
            validate_uuid(event_id, f"event_ids[{index}]")

        if self.status is IntervalStatus.VALID:
            if not isinstance(self.consumption_kwh, Decimal):
                raise TypeError("valid interval consumption_kwh must be a Decimal")
            if not self.consumption_kwh.is_finite() or self.consumption_kwh < 0:
                raise ValueError(
                    "valid interval consumption_kwh must be nonnegative and finite"
                )
            if self.reason is not None or self.event_ids:
                raise ValueError("valid interval cannot have a reason or events")
        else:
            if self.consumption_kwh is not None:
                raise ValueError("invalid interval cannot have consumption_kwh")
            if not isinstance(self.reason, IntervalReason):
                raise TypeError("invalid interval reason must be an IntervalReason")
            if self.reason in _EVENT_REASONS and not self.event_ids:
                raise ValueError("event reason requires event_ids")
            if self.reason not in _EVENT_REASONS and self.event_ids:
                raise ValueError("reading reason cannot have event_ids")


def _validate_order(result: ReadingOrderResult) -> tuple[Reading, ...]:
    if not isinstance(result, ReadingOrderResult):
        raise TypeError("readings must be a ReadingOrderResult")
    if not isinstance(result.ordered, tuple):
        raise TypeError("ordered readings must be a tuple")
    if not isinstance(result.conflicts, tuple):
        raise TypeError("reading conflicts must be a tuple")
    if result.conflicts:
        raise ValueError("reading timestamp conflicts must be resolved first")

    checked = order_readings(result.ordered)
    if checked.conflicts:
        raise ValueError("ordered readings contain a timestamp conflict")
    if checked.ordered != result.ordered:
        raise ValueError("readings must be in chronological order")
    return result.ordered


def _ordered_events(
    events: Iterable[MeterEvent], meter_id: UUID | None
) -> list[MeterEvent]:
    checked: list[MeterEvent] = []
    for index, event in enumerate(events):
        if not isinstance(event, MeterEvent):
            raise TypeError(f"event at index {index} must be a MeterEvent")
        if meter_id is not None and event.meter_id != meter_id:
            raise ValueError(f"event at index {index} belongs to a different meter")
        checked.append(event)
    return sorted(checked, key=lambda event: event.effective_at)


def _event_reason(events: list[MeterEvent]) -> IntervalReason:
    if any(event.approved_by is None for event in events):
        return IntervalReason.UNAPPROVED_EVENT
    if any(
        event.event_type in (MeterEventType.ROLLOVER, MeterEventType.CALIBRATION)
        for event in events
    ):
        return IntervalReason.UNSUPPORTED_EVENT
    return IntervalReason.METER_BOUNDARY


def _make_interval(
    previous: Reading,
    current: Reading,
    status: IntervalStatus,
    *,
    event_ids: tuple[UUID, ...] = (),
    consumption_kwh: Decimal | None = None,
    reason: IntervalReason | None = None,
) -> ConsumptionInterval:
    return ConsumptionInterval(
        meter_id=previous.meter_id,
        previous_reading_id=previous.id,
        current_reading_id=current.id,
        start=previous.recorded_at,
        end=current.recorded_at,
        status=status,
        event_ids=event_ids,
        consumption_kwh=consumption_kwh,
        reason=reason,
    )


def compute_intervals(
    readings: ReadingOrderResult, events: Iterable[MeterEvent]
) -> tuple[ConsumptionInterval, ...]:
    """Calculate exact kWh only for uninterrupted valid reading pairs.

    A conflict invalidates the whole input. A boundary, flagged endpoint, or
    unexplained decrease produces an invalid interval without a kWh value.
    """
    ordered = _validate_order(readings)
    meter_id = ordered[0].meter_id if ordered else None
    ordered_events = _ordered_events(events, meter_id)
    candidates = [
        reading for reading in ordered if reading.status is not ReadingStatus.VOIDED
    ]
    intervals: list[ConsumptionInterval] = []
    event_index = 0

    for previous, current in pairwise(candidates):
        while (
            event_index < len(ordered_events)
            and ordered_events[event_index].effective_at <= previous.recorded_at
        ):
            event_index += 1
        pair_events: list[MeterEvent] = []
        while (
            event_index < len(ordered_events)
            and ordered_events[event_index].effective_at <= current.recorded_at
        ):
            pair_events.append(ordered_events[event_index])
            event_index += 1

        if pair_events:
            intervals.append(
                _make_interval(
                    previous,
                    current,
                    IntervalStatus.INVALID,
                    event_ids=tuple(event.id for event in pair_events),
                    reason=_event_reason(pair_events),
                )
            )
        elif (
            previous.status is ReadingStatus.FLAGGED
            or current.status is ReadingStatus.FLAGGED
        ):
            intervals.append(
                _make_interval(
                    previous,
                    current,
                    IntervalStatus.INVALID,
                    reason=IntervalReason.FLAGGED_READING,
                )
            )
        elif current.cumulative_kwh < previous.cumulative_kwh:
            intervals.append(
                _make_interval(
                    previous,
                    current,
                    IntervalStatus.INVALID,
                    reason=IntervalReason.UNEXPLAINED_DECREASE,
                )
            )
        else:
            intervals.append(
                _make_interval(
                    previous,
                    current,
                    IntervalStatus.VALID,
                    consumption_kwh=calculate_consumption(
                        previous.cumulative_kwh, current.cumulative_kwh
                    ),
                )
            )
    return tuple(intervals)
