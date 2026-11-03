"""Validated reading and meter event domain records."""

from energyiq.readings.intervals import (
    ConsumptionInterval,
    IntervalReason,
    IntervalStatus,
    compute_intervals,
)
from energyiq.readings.models import (
    MeterEvent,
    MeterEventType,
    Reading,
    ReadingSource,
    ReadingStatus,
)
from energyiq.readings.normalization import (
    ConsumptionGap,
    ConsumptionWindowSummary,
    GapReason,
    NormalizedInterval,
    normalize_intervals,
    summarize_consumption,
)
from energyiq.readings.ordering import (
    ReadingConflictEntry,
    ReadingOrderResult,
    ReadingTimestampConflict,
    order_readings,
)

__all__ = [
    "ConsumptionGap",
    "ConsumptionInterval",
    "ConsumptionWindowSummary",
    "GapReason",
    "IntervalReason",
    "IntervalStatus",
    "MeterEvent",
    "MeterEventType",
    "NormalizedInterval",
    "Reading",
    "ReadingConflictEntry",
    "ReadingOrderResult",
    "ReadingSource",
    "ReadingStatus",
    "ReadingTimestampConflict",
    "compute_intervals",
    "normalize_intervals",
    "order_readings",
    "summarize_consumption",
]
