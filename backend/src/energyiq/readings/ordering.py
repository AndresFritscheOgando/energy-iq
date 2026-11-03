"""Stable ordering and timestamp conflict detection for one meter."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from itertools import groupby

from energyiq.readings.models import Reading


@dataclass(frozen=True, slots=True)
class ReadingConflictEntry:
    """One input occurrence of a reading at a conflicting timestamp."""

    input_index: int
    reading: Reading


@dataclass(frozen=True, slots=True)
class ReadingTimestampConflict:
    """All readings recorded at the same UTC instant."""

    recorded_at: datetime
    entries: tuple[ReadingConflictEntry, ...]


@dataclass(frozen=True, slots=True)
class ReadingOrderResult:
    """Every input reading in time order, plus every timestamp conflict."""

    ordered: tuple[Reading, ...]
    conflicts: tuple[ReadingTimestampConflict, ...]


def order_readings(readings: Iterable[Reading]) -> ReadingOrderResult:
    """Order readings for one meter without dropping or changing any occurrence.

    Equal timestamps keep input order. Report every collision across all reading
    statuses. Reject malformed items and readings from another meter with the
    original input index so the caller can correct its input.
    """
    entries: list[ReadingConflictEntry] = []
    expected_meter = None

    for index, reading in enumerate(readings):
        if not isinstance(reading, Reading):
            raise TypeError(f"reading at index {index} must be a Reading")
        if expected_meter is None:
            expected_meter = reading.meter_id
        elif reading.meter_id != expected_meter:
            raise ValueError(f"reading at index {index} belongs to a different meter")
        entries.append(ReadingConflictEntry(index, reading))

    ordered_entries = sorted(entries, key=lambda entry: entry.reading.recorded_at)
    conflicts: list[ReadingTimestampConflict] = []
    for timestamp, group in groupby(
        ordered_entries, key=lambda entry: entry.reading.recorded_at
    ):
        group_entries = tuple(group)
        if len(group_entries) > 1:
            conflicts.append(ReadingTimestampConflict(timestamp, group_entries))
    return ReadingOrderResult(
        ordered=tuple(entry.reading for entry in ordered_entries),
        conflicts=tuple(conflicts),
    )
