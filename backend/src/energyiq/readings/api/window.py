"""One owner scoped consumption window, shared by the consumption and reconciliation routes."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import Session

from energyiq.properties import repository as properties
from energyiq.readings import (
    ConsumptionWindowSummary,
    NormalizedInterval,
    compute_intervals,
    normalize_intervals,
    order_readings,
    summarize_consumption,
)
from energyiq.readings.models import (
    MeterEvent,
    MeterEventType,
    Reading,
    ReadingSource,
    ReadingStatus,
)
from energyiq.readings.persistence import repository


def load_window(
    session: Session,
    owner_id: UUID,
    meter_id: UUID,
    start: datetime,
    end: datetime,
) -> tuple[ConsumptionWindowSummary, list[NormalizedInterval]] | None:
    """Summarize stored readings over ``[start, end)``, or None for a missing meter.

    Run inside the caller's transaction. A foreign or archived meter answers
    None, the same as an unknown one.
    """
    if properties.share_meter_and_property(session, owner_id, meter_id) is None:
        return None
    rows, event_rows = repository.consumption_chain(
        session, owner_id, meter_id, start, end
    )
    readings = [
        Reading(
            id=row.id,
            meter_id=row.meter_id,
            recorded_at=row.recorded_at.astimezone(UTC),
            cumulative_kwh=row.cumulative_kwh,
            source=ReadingSource(row.source),
            status=ReadingStatus(row.status),
            created_at=row.created_at.astimezone(UTC),
            original_local_date=row.original_local_date,
        )
        for row in rows
    ]
    events = [
        MeterEvent(
            id=row.id,
            meter_id=row.meter_id,
            event_type=MeterEventType(row.event_type),
            effective_at=row.effective_at.astimezone(UTC),
            created_at=row.created_at.astimezone(UTC),
            note=row.note,
            approved_by=row.decided_by if row.status == "approved" else None,
            approved_at=row.decided_at.astimezone(UTC)
            if row.status == "approved" and row.decided_at
            else None,
        )
        for row in event_rows
    ]
    ordered = order_readings(readings)
    if ordered.conflicts:
        raise RuntimeError("stored non voided readings share an instant")
    intervals = compute_intervals(ordered, events)
    summary = summarize_consumption(intervals, meter_id, start, end)
    overlapping = [
        item
        for item in normalize_intervals(intervals)
        if item.interval.start < end and item.interval.end > start
    ]
    return summary, overlapping
