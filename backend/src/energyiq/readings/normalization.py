"""Time normalized kWh rates and exact window coverage, with typed gaps.

Nothing here estimates. A span without a trustworthy, fully contained
measurement is reported as a gap, never filled in. Rates and ratios are
computed as exact rationals from integer microseconds and rounded once,
half even, to a declared scale.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, localcontext
from enum import StrEnum
from fractions import Fraction
from uuid import UUID

from energyiq.consumption import exact_kwh_context
from energyiq.observations import validate_utc_timestamp
from energyiq.readings.intervals import (
    ConsumptionInterval,
    IntervalReason,
    IntervalStatus,
)
from energyiq.readings.models import validate_uuid

RATE_PLACES = 6
RATIO_PLACES = 4
_MICROSECONDS_PER_DAY = 86_400_000_000


class GapReason(StrEnum):
    BEFORE_FIRST_READING = "before_first_reading"
    AFTER_LAST_READING = "after_last_reading"
    NO_INTERVALS = "no_intervals"
    PARTIAL_INTERVAL = "partial_interval"
    INVALID_INTERVAL = "invalid_interval"


_INTERVAL_GAP_REASONS = frozenset(
    {GapReason.PARTIAL_INTERVAL, GapReason.INVALID_INTERVAL}
)


def _microseconds(delta: timedelta) -> int:
    """Exact integer microseconds of a timedelta (no float)."""
    return (delta.days * 86_400 + delta.seconds) * 1_000_000 + delta.microseconds


def _round_once(value: Fraction, places: int) -> Decimal:
    """Round an exact rational once, half even, to ``places`` decimals.

    ``Fraction.__round__`` rounds half to even. The Decimal is built from the
    rounded integer as a digit tuple, so no Decimal context can round again.
    """
    scaled = round(value * 10**places)
    digits = tuple(int(digit) for digit in str(abs(scaled)))
    return Decimal((1 if scaled < 0 else 0, digits, -places))


def _validate_scaled(value: Decimal, places: int, label: str) -> None:
    if not isinstance(value, Decimal):
        raise TypeError(f"{label} must be a Decimal")
    if not value.is_finite() or value < 0:
        raise ValueError(f"{label} must be nonnegative and finite")
    if value.as_tuple().exponent != -places:
        raise ValueError(f"{label} must have exactly {places} fractional places")


def _validate_timedelta(value: timedelta, label: str) -> None:
    if not isinstance(value, timedelta):
        raise TypeError(f"{label} must be a timedelta")


@dataclass(frozen=True, slots=True)
class NormalizedInterval:
    """A P1-03 interval with its real duration and kWh per elapsed day."""

    interval: ConsumptionInterval
    duration: timedelta
    kwh_per_day: Decimal | None

    def __post_init__(self) -> None:
        if not isinstance(self.interval, ConsumptionInterval):
            raise TypeError("interval must be a ConsumptionInterval")
        _validate_timedelta(self.duration, "duration")
        if self.duration != self.interval.end - self.interval.start:
            raise ValueError("duration must equal interval end minus start")
        if self.interval.status is IntervalStatus.VALID:
            if self.kwh_per_day is None:
                raise ValueError("valid interval requires kwh_per_day")
            _validate_scaled(self.kwh_per_day, RATE_PLACES, "kwh_per_day")
        elif self.kwh_per_day is not None:
            raise ValueError("invalid interval cannot have kwh_per_day")


@dataclass(frozen=True, slots=True)
class ConsumptionGap:
    """One in window span without a fully measured value, with its cause."""

    start: datetime
    end: datetime
    duration: timedelta
    reason: GapReason
    interval_reason: IntervalReason | None = None
    previous_reading_id: UUID | None = None
    current_reading_id: UUID | None = None
    event_ids: tuple[UUID, ...] = ()

    def __post_init__(self) -> None:
        validate_utc_timestamp(self.start, "start")
        validate_utc_timestamp(self.end, "end")
        if self.end <= self.start:
            raise ValueError("gap end must be after start")
        _validate_timedelta(self.duration, "duration")
        if self.duration != self.end - self.start:
            raise ValueError("duration must equal gap end minus start")
        if not isinstance(self.reason, GapReason):
            raise TypeError("reason must be a GapReason")

        if self.reason is GapReason.INVALID_INTERVAL:
            if not isinstance(self.interval_reason, IntervalReason):
                raise TypeError("invalid_interval gap requires an IntervalReason")
        elif self.interval_reason is not None:
            raise ValueError("only an invalid_interval gap has an interval_reason")

        if self.reason in _INTERVAL_GAP_REASONS:
            validate_uuid(self.previous_reading_id, "previous_reading_id")  # type: ignore[arg-type]
            validate_uuid(self.current_reading_id, "current_reading_id")  # type: ignore[arg-type]
        elif (
            self.previous_reading_id is not None or self.current_reading_id is not None
        ):
            raise ValueError("only interval gaps have reading ids")

        if not isinstance(self.event_ids, tuple):
            raise TypeError("event_ids must be a tuple")
        for index, event_id in enumerate(self.event_ids):
            validate_uuid(event_id, f"event_ids[{index}]")
        if self.event_ids and self.reason is not GapReason.INVALID_INTERVAL:
            raise ValueError("only an invalid_interval gap has event_ids")


@dataclass(frozen=True, slots=True)
class ConsumptionWindowSummary:
    """Measured kWh, exact coverage, and typed gaps for a half open window."""

    meter_id: UUID
    window_start: datetime
    window_end: datetime
    measured_kwh: Decimal
    covered: timedelta
    uncovered: timedelta
    coverage_ratio: Decimal
    average_kwh_per_day: Decimal | None
    measured_intervals: tuple[NormalizedInterval, ...]
    gaps: tuple[ConsumptionGap, ...]

    def __post_init__(self) -> None:
        validate_uuid(self.meter_id, "meter_id")
        validate_utc_timestamp(self.window_start, "window_start")
        validate_utc_timestamp(self.window_end, "window_end")
        if self.window_end <= self.window_start:
            raise ValueError("window_end must be after window_start")
        if not isinstance(self.measured_kwh, Decimal):
            raise TypeError("measured_kwh must be a Decimal")
        if not self.measured_kwh.is_finite() or self.measured_kwh < 0:
            raise ValueError("measured_kwh must be nonnegative and finite")
        for label in ("covered", "uncovered"):
            value: timedelta = getattr(self, label)
            _validate_timedelta(value, label)
            if value < timedelta(0):
                raise ValueError(f"{label} cannot be negative")
        if self.covered + self.uncovered != self.window_end - self.window_start:
            raise ValueError("covered plus uncovered must equal the window length")
        _validate_scaled(self.coverage_ratio, RATIO_PLACES, "coverage_ratio")
        if self.coverage_ratio > 1:
            raise ValueError("coverage_ratio cannot exceed 1")
        if self.covered == timedelta(0):
            if self.average_kwh_per_day is not None:
                raise ValueError("average_kwh_per_day must be None without coverage")
        elif self.average_kwh_per_day is None:
            raise ValueError("average_kwh_per_day is required with coverage")
        else:
            _validate_scaled(
                self.average_kwh_per_day, RATE_PLACES, "average_kwh_per_day"
            )

        if not isinstance(self.measured_intervals, tuple):
            raise TypeError("measured_intervals must be a tuple")
        for index, item in enumerate(self.measured_intervals):
            if not isinstance(item, NormalizedInterval):
                raise TypeError(
                    f"measured_intervals[{index}] must be a NormalizedInterval"
                )
            if item.interval.status is not IntervalStatus.VALID:
                raise ValueError(f"measured_intervals[{index}] must be valid")
        if not isinstance(self.gaps, tuple):
            raise TypeError("gaps must be a tuple")
        for index, gap in enumerate(self.gaps):
            if not isinstance(gap, ConsumptionGap):
                raise TypeError(f"gaps[{index}] must be a ConsumptionGap")


def _validate_chain(
    intervals: Iterable[ConsumptionInterval], meter_id: UUID | None
) -> tuple[ConsumptionInterval, ...]:
    """Materialize once and require one meter and an end to start chain.

    ``meter_id`` None means the chain's meter is taken from the first item.
    """
    chain = tuple(intervals)
    for index, item in enumerate(chain):
        if not isinstance(item, ConsumptionInterval):
            raise TypeError(f"interval at index {index} must be a ConsumptionInterval")
    expected_meter = (
        meter_id if meter_id is not None or not chain else chain[0].meter_id
    )
    for index, item in enumerate(chain):
        if item.meter_id != expected_meter:
            raise ValueError(f"interval at index {index} belongs to a different meter")
        if index:
            previous_end = chain[index - 1].end
            if item.start > previous_end:
                raise ValueError(
                    f"interval at index {index} leaves a hole after the previous interval"
                )
            if item.start < previous_end:
                raise ValueError(
                    f"interval at index {index} overlaps the previous interval"
                )
    return chain


def _normalize(interval: ConsumptionInterval) -> NormalizedInterval:
    duration = interval.end - interval.start
    rate: Decimal | None = None
    if interval.status is IntervalStatus.VALID:
        assert interval.consumption_kwh is not None
        rate = _round_once(
            Fraction(interval.consumption_kwh)
            * _MICROSECONDS_PER_DAY
            / _microseconds(duration),
            RATE_PLACES,
        )
    return NormalizedInterval(interval=interval, duration=duration, kwh_per_day=rate)


def normalize_intervals(
    intervals: Iterable[ConsumptionInterval],
) -> tuple[NormalizedInterval, ...]:
    """Return kWh per elapsed day for each interval, in input order.

    A day is 86,400 seconds of elapsed UTC time. Valid intervals get a rate
    rounded once, half even, to 6 places; invalid intervals get None. The
    input must be one meter's complete, touching ``compute_intervals`` chain;
    anything else raises an indexed TypeError or ValueError. An iterator is
    consumed once and no input record is modified.
    """
    return tuple(_normalize(item) for item in _validate_chain(intervals, None))


def _gap(
    start: datetime,
    end: datetime,
    reason: GapReason,
    interval: ConsumptionInterval | None = None,
) -> ConsumptionGap:
    if interval is None:
        return ConsumptionGap(start=start, end=end, duration=end - start, reason=reason)
    invalid = reason is GapReason.INVALID_INTERVAL
    return ConsumptionGap(
        start=start,
        end=end,
        duration=end - start,
        reason=reason,
        interval_reason=interval.reason if invalid else None,
        previous_reading_id=interval.previous_reading_id,
        current_reading_id=interval.current_reading_id,
        event_ids=interval.event_ids if invalid else (),
    )


def summarize_consumption(
    intervals: Iterable[ConsumptionInterval],
    meter_id: UUID,
    window_start: datetime,
    window_end: datetime,
) -> ConsumptionWindowSummary:
    """Summarize measured kWh and coverage over ``[window_start, window_end)``.

    Only valid intervals fully inside the window are measured. Every other
    part of the window is a typed gap: before the first reading, after the
    last, no intervals at all, the in window part of a valid interval that
    crosses a bound, or the in window part of an invalid interval. Measured
    intervals and gaps tile the window exactly. Missing data never raises.
    """
    validate_uuid(meter_id, "meter_id")
    validate_utc_timestamp(window_start, "window_start")
    validate_utc_timestamp(window_end, "window_end")
    if window_end <= window_start:
        raise ValueError("window_end must be after window_start")
    chain = _validate_chain(intervals, meter_id)

    measured: list[NormalizedInterval] = []
    gaps: list[ConsumptionGap] = []
    if not chain:
        gaps.append(_gap(window_start, window_end, GapReason.NO_INTERVALS))
    else:
        data_start = chain[0].start
        data_end = chain[-1].end
        if window_start < data_start:
            gaps.append(
                _gap(
                    window_start,
                    min(data_start, window_end),
                    GapReason.BEFORE_FIRST_READING,
                )
            )
        for interval in chain:
            if interval.end <= window_start:
                continue
            if interval.start >= window_end:
                break
            inside = interval.start >= window_start and interval.end <= window_end
            if interval.status is IntervalStatus.VALID and inside:
                measured.append(_normalize(interval))
                continue
            reason = (
                GapReason.PARTIAL_INTERVAL
                if interval.status is IntervalStatus.VALID
                else GapReason.INVALID_INTERVAL
            )
            gaps.append(
                _gap(
                    max(interval.start, window_start),
                    min(interval.end, window_end),
                    reason,
                    interval,
                )
            )
        if window_end > data_end:
            gaps.append(
                _gap(
                    max(data_end, window_start),
                    window_end,
                    GapReason.AFTER_LAST_READING,
                )
            )

    measured_kwh = Decimal(0)
    with localcontext(exact_kwh_context()):
        for item in measured:
            assert item.interval.consumption_kwh is not None
            measured_kwh += item.interval.consumption_kwh

    covered = sum((item.duration for item in measured), timedelta(0))
    uncovered = sum((gap.duration for gap in gaps), timedelta(0))
    covered_us = _microseconds(covered)
    window_us = _microseconds(window_end - window_start)
    average = (
        None
        if covered_us == 0
        else _round_once(
            Fraction(measured_kwh) * _MICROSECONDS_PER_DAY / covered_us, RATE_PLACES
        )
    )
    return ConsumptionWindowSummary(
        meter_id=meter_id,
        window_start=window_start,
        window_end=window_end,
        measured_kwh=measured_kwh,
        covered=covered,
        uncovered=uncovered,
        coverage_ratio=_round_once(Fraction(covered_us, window_us), RATIO_PLACES),
        average_kwh_per_day=average,
        measured_intervals=tuple(measured),
        gaps=tuple(gaps),
    )
