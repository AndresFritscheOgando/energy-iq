from datetime import UTC, date, datetime, timedelta, timezone, tzinfo
from decimal import Decimal
from typing import cast

import pytest

from energyiq.observations import Observation, elapsed_hours, sort_observations


def test_elapsed_hours_within_one_day():
    previous_at = datetime(2026, 11, 1, 8, 0, tzinfo=UTC)
    current_at = datetime(2026, 11, 1, 20, 0, tzinfo=UTC)

    result = elapsed_hours(previous_at, current_at)

    assert result == 12.0
    assert isinstance(result, float)


def test_elapsed_hours_includes_complete_days():
    previous_at = datetime(2026, 11, 1, 8, 0, tzinfo=UTC)
    current_at = datetime(2026, 11, 2, 20, 0, tzinfo=UTC)

    assert elapsed_hours(previous_at, current_at) == 36.0


def test_elapsed_hours_preserves_fractional_hours():
    previous_at = datetime(2026, 11, 1, 8, 0, tzinfo=UTC)
    current_at = datetime(2026, 11, 1, 8, 30, tzinfo=UTC)

    assert elapsed_hours(previous_at, current_at) == 0.5


def test_equal_timestamps_raise_value_error():
    timestamp = datetime(2026, 11, 1, 8, 0, tzinfo=UTC)

    with pytest.raises(ValueError):
        elapsed_hours(timestamp, timestamp)


def test_reversed_timestamps_raise_value_error():
    previous_at = datetime(2026, 11, 1, 20, 0, tzinfo=UTC)
    current_at = datetime(2026, 11, 1, 8, 0, tzinfo=UTC)

    with pytest.raises(ValueError):
        elapsed_hours(previous_at, current_at)


def test_naive_previous_timestamp_raises_value_error():
    previous_at = datetime(2026, 11, 1, 8, 0)
    current_at = datetime(2026, 11, 1, 20, 0, tzinfo=UTC)

    with pytest.raises(ValueError):
        elapsed_hours(previous_at, current_at)


def test_naive_current_timestamp_raises_value_error():
    previous_at = datetime(2026, 11, 1, 8, 0, tzinfo=UTC)
    current_at = datetime(2026, 11, 1, 20, 0)

    with pytest.raises(ValueError):
        elapsed_hours(previous_at, current_at)


def test_two_naive_timestamps_raise_value_error():
    previous_at = datetime(2026, 11, 1, 8, 0)
    current_at = datetime(2026, 11, 1, 20, 0)

    with pytest.raises(ValueError):
        elapsed_hours(previous_at, current_at)


def test_non_utc_previous_timestamp_raises_value_error():
    previous_at = datetime(2026, 11, 1, 8, 0, tzinfo=timezone(timedelta(hours=3)))
    current_at = datetime(2026, 11, 1, 20, 0, tzinfo=UTC)

    with pytest.raises(ValueError):
        elapsed_hours(previous_at, current_at)


def test_non_utc_current_timestamp_raises_value_error():
    previous_at = datetime(2026, 11, 1, 8, 0, tzinfo=UTC)
    current_at = datetime(2026, 11, 1, 20, 0, tzinfo=timezone(timedelta(hours=-4)))

    with pytest.raises(ValueError):
        elapsed_hours(previous_at, current_at)


def test_two_non_utc_timestamps_raise_value_error():
    offset = timezone(timedelta(hours=-4))
    previous_at = datetime(2026, 11, 1, 8, 0, tzinfo=offset)
    current_at = datetime(2026, 11, 1, 20, 0, tzinfo=offset)

    with pytest.raises(ValueError):
        elapsed_hours(previous_at, current_at)


def test_zero_offset_timezone_is_accepted_regardless_of_name():
    offset = timezone(timedelta(0), "Zero offset")
    previous_at = datetime(2026, 11, 1, 8, 0, tzinfo=offset)
    current_at = datetime(2026, 11, 1, 20, 0, tzinfo=offset)

    assert elapsed_hours(previous_at, current_at) == 12.0


def test_sort_empty_observations_returns_a_new_empty_list():
    observations: list[Observation] = []

    result = sort_observations(observations)

    assert result == []
    assert result is not observations


def test_sort_single_observation_returns_a_new_list():
    observation = (datetime(2026, 11, 1, 8, tzinfo=UTC), Decimal("100.1"))
    observations = [observation]

    result = sort_observations(observations)

    assert result == [observation]
    assert result is not observations


@pytest.mark.parametrize("order", [(0, 1, 2), (2, 1, 0), (1, 2, 0)])
def test_sort_preserves_pairs_and_leaves_input_unchanged(order: tuple[int, ...]):
    expected: list[Observation] = [
        (datetime(2026, 10, 31, 23, tzinfo=UTC), Decimal("100.1")),
        (datetime(2026, 11, 1, 8, tzinfo=UTC), Decimal("105.3")),
        (datetime(2026, 11, 2, 8, tzinfo=UTC), Decimal("142.2")),
    ]
    observations = [expected[index] for index in order]
    original = observations.copy()

    result = sort_observations(observations)

    assert result == expected
    assert observations == original
    assert result is not observations


def test_sort_equal_timestamps_preserves_input_order_instead_of_sorting_by_kwh():
    earlier = (datetime(2026, 11, 1, 7, tzinfo=UTC), Decimal("80.0"))
    timestamp = datetime(2026, 11, 1, 8, tzinfo=UTC)
    first_equal = (timestamp, Decimal("120.5"))
    second_equal = (timestamp, Decimal("100.1"))
    observations = [first_equal, earlier, second_equal]

    assert sort_observations(observations) == [earlier, first_equal, second_equal]


def test_sort_preserves_exact_duplicate_observations():
    observation = (datetime(2026, 11, 1, 8, tzinfo=UTC), Decimal("100.1"))

    assert sort_observations([observation, observation]) == [
        observation,
        observation,
    ]


def test_sort_accepts_a_single_pass_iterable():
    earlier = (datetime(2026, 11, 1, 8, tzinfo=UTC), Decimal("100.1"))
    later = (datetime(2026, 11, 2, 8, tzinfo=UTC), Decimal("142.2"))
    observations = (observation for observation in (later, earlier))

    assert sort_observations(observations) == [earlier, later]


def test_sort_accepts_mixed_named_zero_offset_timezones():
    offset = timezone(timedelta(0), "Zero offset")
    earlier = (datetime(2026, 11, 1, 8, tzinfo=offset), Decimal("100.1"))
    later = (datetime(2026, 11, 2, 8, tzinfo=UTC), Decimal("142.2"))

    assert sort_observations((later, earlier)) == [earlier, later]


@pytest.mark.parametrize("index", [0, 1, 2])
@pytest.mark.parametrize(
    "offset",
    [None, timezone(timedelta(hours=3)), timezone(timedelta(hours=-4))],
    ids=["naive", "east", "west"],
)
def test_sort_rejects_invalid_timezones_before_sorting_without_mutating_input(
    index: int, offset: timezone | None
):
    observations: list[Observation] = [
        (datetime(2026, 11, 2, 8, tzinfo=UTC), Decimal("142.2")),
        (datetime(2026, 11, 1, 8, tzinfo=UTC), Decimal("100.1")),
    ]
    observations.insert(
        index, (datetime(2026, 11, 1, 12, tzinfo=offset), Decimal("120.5"))
    )
    original = observations.copy()
    reason = "timezone information" if offset is None else "zero UTC offset"

    with pytest.raises(ValueError, match=f"index {index}.*{reason}"):
        sort_observations(observations)

    assert observations == original


@pytest.mark.parametrize(
    "offset",
    [None, timezone(timedelta(hours=3)), timezone(timedelta(hours=-4))],
    ids=["naive", "east", "west"],
)
def test_sort_validates_timezone_even_for_one_observation(offset: timezone | None):
    observation = (datetime(2026, 11, 1, 8, tzinfo=offset), Decimal("100.1"))

    with pytest.raises(ValueError, match="index 0"):
        sort_observations([observation])


@pytest.mark.parametrize("position", [0, 1], ids=["previous", "current"])
@pytest.mark.parametrize("invalid", [None, "2026-11-02", 1, True, date(2026, 11, 2)])
def test_elapsed_hours_rejects_unsupported_types(position: int, invalid: object):
    timestamps = [
        datetime(2026, 11, 1, tzinfo=UTC),
        datetime(2026, 11, 2, tzinfo=UTC),
    ]
    timestamps[position] = cast(datetime, invalid)
    label = "previous" if position == 0 else "current"

    with pytest.raises(TypeError, match=f"{label} timestamp must be a datetime"):
        elapsed_hours(*timestamps)


@pytest.mark.parametrize("invalid", [None, "2026-11-02", 1, True, date(2026, 11, 2)])
def test_sort_rejects_unsupported_timestamp_even_in_singleton(invalid: object):
    observations = [cast(Observation, (invalid, Decimal(1)))]
    original = observations.copy()

    with pytest.raises(TypeError, match="index 0.*datetime"):
        sort_observations(observations)

    assert observations == original


@pytest.mark.parametrize("index", [0, 1, 2])
@pytest.mark.parametrize("invalid", [None, 1, (), (1,), (1, 2, 3)])
def test_sort_reports_indexed_pair_errors_without_mutation(index: int, invalid: object):
    observations = [
        (datetime(2026, 11, 2, tzinfo=UTC), Decimal(2)),
        (datetime(2026, 11, 1, tzinfo=UTC), Decimal(1)),
    ]
    observations.insert(index, cast(Observation, invalid))
    original = observations.copy()

    with pytest.raises(TypeError, match=f"index {index}.*timestamp/value pair"):
        sort_observations(observations)

    assert observations == original


def test_sort_preserves_list_pairs_and_does_not_validate_kwh():
    first = [datetime(2026, 11, 1, tzinfo=UTC), Decimal("NaN")]
    second = [datetime(2026, 11, 2, tzinfo=UTC), Decimal(-1)]
    result = sort_observations(cast(list[Observation], [second, first]))

    assert result[0] is first
    assert result[1] is second


def test_sort_does_not_mask_outer_iterable_failure():
    def broken_observations():
        yield (datetime(2026, 11, 1, tzinfo=UTC), Decimal(1))
        raise ValueError("source failed")

    with pytest.raises(ValueError, match="source failed"):
        sort_observations(broken_observations())


def test_custom_timezone_errors_propagate():
    class BrokenTimezone(tzinfo):
        def utcoffset(self, dt: datetime | None) -> timedelta | None:
            raise RuntimeError("timezone failed")

    timestamp = datetime(2026, 11, 1, tzinfo=BrokenTimezone())
    with pytest.raises(RuntimeError, match="timezone failed"):
        elapsed_hours(timestamp, datetime(2026, 11, 2, tzinfo=UTC))
    with pytest.raises(RuntimeError, match="timezone failed"):
        sort_observations([(timestamp, Decimal(1))])


def test_elapsed_hours_preserves_microsecond_and_leap_day_duration():
    previous = datetime(2024, 2, 28, 23, 59, 59, 999999, tzinfo=UTC)
    current = datetime(2024, 2, 29, tzinfo=UTC)

    assert elapsed_hours(previous, current) == pytest.approx(1e-6 / 3600)
