"""Translate between the HTTP contract and the readings domain."""

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from energyiq.platform.http.formats import format_decimal, format_duration, format_utc
from energyiq.readings import (
    ConsumptionGap,
    ConsumptionWindowSummary,
    IntervalStatus,
    MeterEvent,
    NormalizedInterval,
    Reading,
    ReadingTimestampConflict,
)
from energyiq.readings.api.schemas import (
    ConflictEntryOut,
    ConflictOut,
    ConsumptionSummaryRequest,
    ConsumptionSummaryResponse,
    DuplicateIdOut,
    GapOut,
    IntervalOut,
    WindowOut,
)


def _repeated(
    collection: str, ids: Sequence[UUID]
) -> list[tuple[str, UUID, list[int]]]:
    indexes: dict[UUID, list[int]] = {}
    for index, item_id in enumerate(ids):
        indexes.setdefault(item_id, []).append(index)
    return [
        (collection, item_id, found)
        for item_id, found in indexes.items()
        if len(found) > 1
    ]


def find_duplicate_ids(request: ConsumptionSummaryRequest) -> list[DuplicateIdOut]:
    """Every id repeated within readings or within events, in first seen order.

    A reading and an event may share an id; they are separate collections.
    """
    repeated = _repeated("readings", [item.id for item in request.readings])
    repeated += _repeated("events", [item.id for item in request.events])
    return [
        DuplicateIdOut.model_validate(
            {"collection": collection, "id": item_id, "input_indexes": found}
        )
        for collection, item_id, found in repeated
    ]


def to_domain(
    request: ConsumptionSummaryRequest, created_at: datetime
) -> tuple[list[Reading], list[MeterEvent]]:
    """Domain records for a validated request, all stamped ``created_at``."""
    readings = [
        Reading(
            id=item.id,
            meter_id=request.meter_id,
            recorded_at=item.recorded_at,
            cumulative_kwh=Decimal(item.cumulative_kwh),
            source=item.source,
            status=item.status,
            created_at=created_at,
        )
        for item in request.readings
    ]
    events = [
        MeterEvent(
            id=item.id,
            meter_id=request.meter_id,
            event_type=item.event_type,
            effective_at=item.effective_at,
            created_at=created_at,
            approved_by=item.approved_by,
            approved_at=item.approved_at,
        )
        for item in request.events
    ]
    return readings, events


def conflicts_out(
    conflicts: Sequence[ReadingTimestampConflict],
) -> list[ConflictOut]:
    """Every P1-02 conflict group, with the input index of each entry."""
    return [
        ConflictOut(
            recorded_at=format_utc(conflict.recorded_at),
            entries=[
                ConflictEntryOut(
                    input_index=entry.input_index,
                    reading_id=entry.reading.id,
                    status=entry.reading.status,
                )
                for entry in conflict.entries
            ],
        )
        for conflict in conflicts
    ]


def _optional_decimal(value: Decimal | None) -> str | None:
    return None if value is None else format_decimal(value)


def _gap_out(gap: ConsumptionGap) -> GapOut:
    return GapOut(
        start=format_utc(gap.start),
        end=format_utc(gap.end),
        duration=format_duration(gap.duration),
        reason=gap.reason,
        interval_reason=gap.interval_reason,
        previous_reading_id=gap.previous_reading_id,
        current_reading_id=gap.current_reading_id,
        event_ids=list(gap.event_ids),
    )


def _interval_out(
    item: NormalizedInterval, window_start: datetime, window_end: datetime
) -> IntervalOut:
    interval = item.interval
    measured = (
        interval.status is IntervalStatus.VALID
        and interval.start >= window_start
        and interval.end <= window_end
    )
    return IntervalOut(
        previous_reading_id=interval.previous_reading_id,
        current_reading_id=interval.current_reading_id,
        start=format_utc(interval.start),
        end=format_utc(interval.end),
        duration=format_duration(item.duration),
        status=interval.status,
        reason=interval.reason,
        event_ids=list(interval.event_ids),
        consumption_kwh=_optional_decimal(interval.consumption_kwh),
        kwh_per_day=_optional_decimal(item.kwh_per_day),
        measured_in_window=measured,
    )


def to_response(
    summary: ConsumptionWindowSummary,
    intervals: Sequence[NormalizedInterval],
) -> ConsumptionSummaryResponse:
    """Render the domain summary and the whole interval chain as text values."""
    return ConsumptionSummaryResponse(
        meter_id=summary.meter_id,
        window=WindowOut(
            start=format_utc(summary.window_start),
            end=format_utc(summary.window_end),
        ),
        measured_kwh=format_decimal(summary.measured_kwh),
        covered=format_duration(summary.covered),
        uncovered=format_duration(summary.uncovered),
        coverage_ratio=format_decimal(summary.coverage_ratio),
        average_kwh_per_day=_optional_decimal(summary.average_kwh_per_day),
        gaps=[_gap_out(gap) for gap in summary.gaps],
        intervals=[
            _interval_out(item, summary.window_start, summary.window_end)
            for item in intervals
        ],
    )
