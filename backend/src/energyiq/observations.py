from collections.abc import Iterable
from datetime import datetime, timedelta
from decimal import Decimal

type Observation = tuple[datetime, Decimal]


def validate_utc_timestamp(timestamp: datetime, label: str) -> None:
    if not isinstance(timestamp, datetime):
        raise TypeError(f"{label} must be a datetime")
    offset = timestamp.utcoffset()
    if offset is None:
        raise ValueError(f"{label} must include timezone information")
    if offset != timedelta(0):
        raise ValueError(f"{label} must have a zero UTC offset")


def sort_observations(observations: Iterable[Observation]) -> list[Observation]:
    """Return a chronological copy of timestamp/value pairs for one meter.

    Require datetime timestamps with timezone information and zero UTC offsets.
    Raise indexed TypeError for malformed pairs or unsupported timestamp types,
    and ValueError for invalid timezones.
    Preserve each pair and the input order of equal timestamps, including exact
    duplicates. Do not validate kWh values, resolve duplicates, or infer intervals.
    The input collection is not modified; an iterator is consumed once.
    """
    ordered = list(observations)
    for index, observation in enumerate(ordered):
        try:
            timestamp, _ = observation
        except (TypeError, ValueError):
            raise TypeError(
                f"observation at index {index} must be a timestamp/value pair"
            ) from None
        validate_utc_timestamp(timestamp, f"observation at index {index}")

    return sorted(ordered, key=lambda observation: observation[0])


def elapsed_hours(previous_at: datetime, current_at: datetime) -> float:
    """Return elapsed hours between strictly increasing UTC timestamps.

    Raise TypeError for non datetime inputs and ValueError for naive timestamps,
    nonzero UTC offsets, or a current timestamp that is not later than previous.
    """
    validate_utc_timestamp(previous_at, "previous timestamp")
    validate_utc_timestamp(current_at, "current timestamp")

    if current_at <= previous_at:
        raise ValueError("current timestamp must be later than previous timestamp")

    return (current_at - previous_at).total_seconds() / 3600
