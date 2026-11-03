from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest

from energyiq.readings import (
    Reading,
    ReadingSource,
    ReadingStatus,
    order_readings,
)

METER_ID = UUID(int=100)
OTHER_METER_ID = UUID(int=200)
START = datetime(2026, 11, 3, 12, tzinfo=UTC)


def make_reading(
    number: int,
    minutes: int,
    *,
    meter_id: UUID = METER_ID,
    status: ReadingStatus = ReadingStatus.VALID,
) -> Reading:
    return Reading(
        id=UUID(int=number),
        meter_id=meter_id,
        recorded_at=START + timedelta(minutes=minutes),
        cumulative_kwh=Decimal("13007.10"),
        source=ReadingSource.MANUAL,
        status=status,
        created_at=START,
    )


# covers: AC-1, AC-3
def test_orders_readings_stably_without_changing_input():
    later = make_reading(1, 20)
    first_at_start = make_reading(2, 0)
    second_at_start = make_reading(3, 0)
    input_readings = [later, first_at_start, second_at_start]

    result = order_readings(input_readings)

    assert result.ordered == (first_at_start, second_at_start, later)
    assert input_readings == [later, first_at_start, second_at_start]
    assert result.conflicts[0].entries[0].reading is first_at_start
    assert result.conflicts[0].entries[1].reading is second_at_start


# covers: AC-2, AC-3
def test_reports_every_conflict_with_original_positions_and_statuses():
    late_valid = make_reading(1, 30)
    early_voided = make_reading(2, 0, status=ReadingStatus.VOIDED)
    late_flagged = make_reading(3, 30, status=ReadingStatus.FLAGGED)
    early_valid = make_reading(4, 0)
    input_readings = [late_valid, early_voided, late_flagged, early_valid]

    result = order_readings(input_readings)

    assert result.ordered == (early_voided, early_valid, late_valid, late_flagged)
    assert tuple(group.recorded_at for group in result.conflicts) == (
        START,
        START + timedelta(minutes=30),
    )
    assert tuple(entry.input_index for entry in result.conflicts[0].entries) == (1, 3)
    assert tuple(entry.input_index for entry in result.conflicts[1].entries) == (0, 2)
    assert tuple(entry.reading for entry in result.conflicts[0].entries) == (
        early_voided,
        early_valid,
    )


# covers: AC-2, AC-3
def test_repeated_same_instance_is_a_separate_occurrence():
    reading = make_reading(1, 0)

    result = order_readings([reading, reading, reading])

    assert len(result.ordered) == 3
    assert len(result.conflicts) == 1
    assert tuple(entry.input_index for entry in result.conflicts[0].entries) == (
        0,
        1,
        2,
    )
    assert all(entry.reading is reading for entry in result.conflicts[0].entries)


# covers: AC-2
def test_distinct_readings_with_equal_values_still_conflict():
    first = make_reading(1, 0)
    second = make_reading(2, 0)

    result = order_readings((first, second))

    assert len(result.conflicts) == 1
    assert result.conflicts[0].entries[0].reading is first
    assert result.conflicts[0].entries[1].reading is second


# covers: AC-1
def test_empty_singleton_and_unique_input_have_no_conflicts():
    reading = make_reading(1, 0)

    assert order_readings([]).ordered == ()
    assert order_readings([]).conflicts == ()
    assert order_readings([reading]).ordered == (reading,)
    assert order_readings([reading]).conflicts == ()
    assert order_readings([make_reading(2, 5), reading]).conflicts == ()


# covers: AC-3
def test_consumes_a_one_pass_iterable_once():
    readings = [make_reading(1, 10), make_reading(2, 0)]
    consumed = 0

    def one_pass():
        nonlocal consumed
        for reading in readings:
            consumed += 1
            yield reading

    result = order_readings(one_pass())

    assert consumed == 2
    assert result.ordered == (readings[1], readings[0])


@pytest.mark.parametrize("bad_value", [None, 1, "reading", (START, Decimal(1))])
# covers: AC-4
def test_rejects_non_reading_item_with_original_index(bad_value: object):
    with pytest.raises(TypeError, match="reading at index 1.*Reading"):
        order_readings([make_reading(1, 0), bad_value])  # type: ignore[list-item]


# covers: AC-4
def test_rejects_a_different_meter_with_original_index():
    with pytest.raises(ValueError, match="reading at index 2.*different meter"):
        order_readings(
            [
                make_reading(1, 10),
                make_reading(2, 0),
                make_reading(3, 20, meter_id=OTHER_METER_ID),
            ]
        )


# covers: AC-3
def test_result_records_are_immutable():
    result = order_readings([make_reading(1, 0), make_reading(2, 0)])

    with pytest.raises(FrozenInstanceError):
        result.ordered = ()  # pyright: ignore[reportAttributeAccessIssue]
    with pytest.raises(FrozenInstanceError):
        result.conflicts[0].recorded_at = START  # pyright: ignore[reportAttributeAccessIssue]
    with pytest.raises(FrozenInstanceError):
        result.conflicts[0].entries[0].input_index = 4  # pyright: ignore[reportAttributeAccessIssue]


# covers: AC-2, AC-3
def test_conflict_includes_flagged_and_voided_readings_without_a_valid_reading():
    flagged = make_reading(1, 0, status=ReadingStatus.FLAGGED)
    voided = make_reading(2, 0, status=ReadingStatus.VOIDED)

    result = order_readings([flagged, voided])

    assert result.ordered == (flagged, voided)
    assert tuple(entry.reading for entry in result.conflicts[0].entries) == (
        flagged,
        voided,
    )


# covers: AC-3
def test_iterable_is_not_traversed_twice():
    first = make_reading(1, 10)
    second = make_reading(2, 0)

    class SingleTraversal:
        def __init__(self):
            self.traversals = 0

        def __iter__(self):
            self.traversals += 1
            if self.traversals > 1:
                raise AssertionError("input traversed twice")
            yield first
            yield second

    source = SingleTraversal()

    result = order_readings(source)

    assert source.traversals == 1
    assert result.ordered == (second, first)
