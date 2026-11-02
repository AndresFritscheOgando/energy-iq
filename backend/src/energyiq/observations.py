from collections.abc import Iterable
from datetime import datetime, timedelta
from decimal import Decimal

type Observation = tuple[datetime, Decimal]


def sort_observations(observations: Iterable[Observation]) -> list[Observation]:
    """Return a chronological copy of timestamp/value pairs for one meter.

    Require timezone-aware, zero-offset timestamps; otherwise raise ValueError.
    Preserve each pair and the input order of equal timestamps, including exact
    duplicates. Do not validate kWh values, resolve duplicates, or infer intervals.
    The input collection is not modified; an iterator is consumed once.
    """
    ordered = list(observations)
    for index, (timestamp, _) in enumerate(ordered):
        offset = timestamp.utcoffset()
        if offset is None:
            raise ValueError(
                f"observation at index {index} must include timezone information"
            )
        if offset != timedelta(0):
            raise ValueError(
                f"observation at index {index} must have a zero UTC offset"
            )

    return sorted(ordered, key=lambda observation: observation[0])


def elapsed_hours(previous_at: datetime, current_at: datetime) -> float:
    """Return elapsed hours between strictly increasing UTC timestamps.

    Raise ValueError for naive timestamps, nonzero UTC offsets, or a current
    timestamp that is not later than the previous timestamp.
    """
    previous_offset = previous_at.utcoffset()
    current_offset = current_at.utcoffset()

    if previous_offset is None:
        raise ValueError("previous timestamp must include timezone information")

    if current_offset is None:
        raise ValueError("current timestamp must include timezone information")

    if previous_offset != timedelta(0):
        raise ValueError("previous timestamp must have a zero UTC offset")

    if current_offset != timedelta(0):
        raise ValueError("current timestamp must have a zero UTC offset")

    if current_at <= previous_at:
        raise ValueError("current timestamp must be later than previous timestamp")

    return (current_at - previous_at).total_seconds() / 3600
