from collections.abc import Iterator
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from decimal import Decimal, getcontext, localcontext
from typing import Any
from uuid import UUID

import pytest

from energyiq.readings import (
    ConsumptionInterval,
    IntervalReason,
    IntervalStatus,
    MeterEvent,
    MeterEventType,
    Reading,
    ReadingOrderResult,
    ReadingSource,
    ReadingStatus,
    compute_intervals,
    order_readings,
)

METER = UUID(int=100)
OTHER_METER = UUID(int=200)
ACTOR = UUID(int=300)
START = datetime(2026, 11, 3, 12, tzinfo=UTC)


def reading(
    number: int,
    minutes: int,
    value: str,
    *,
    status: ReadingStatus = ReadingStatus.VALID,
    meter_id: UUID = METER,
) -> Reading:
    return Reading(
        id=UUID(int=number),
        meter_id=meter_id,
        recorded_at=START + timedelta(minutes=minutes),
        cumulative_kwh=Decimal(value),
        source=ReadingSource.MANUAL,
        status=status,
        created_at=START,
    )


def event(
    number: int,
    minutes: int,
    kind: MeterEventType = MeterEventType.RESET,
    *,
    approved: bool = True,
    meter_id: UUID = METER,
) -> MeterEvent:
    return MeterEvent(
        id=UUID(int=number),
        meter_id=meter_id,
        event_type=kind,
        effective_at=START + timedelta(minutes=minutes),
        created_at=START,
        approved_by=ACTOR if approved else None,
        approved_at=START if approved else None,
    )


def calculate(readings: list[Reading], events: object = ()):
    return compute_intervals(order_readings(readings), events)  # type: ignore[arg-type]


def test_exact_and_zero_intervals_preserve_decimal_context():
    readings = [
        reading(1, 0, "13007.10"),
        reading(2, 60, "13049.10"),
        reading(3, 120, "13049.10"),
    ]
    with localcontext() as context:
        context.prec = 3
        before = context.copy()
        result = calculate(readings)
        assert context.prec == before.prec
        assert context.rounding == before.rounding
        assert context.flags == before.flags
        assert context.traps == before.traps

    assert len(result) == 2
    assert result[0].consumption_kwh == Decimal("42.00")
    assert result[1].consumption_kwh == Decimal("0.00")
    assert all(interval.status is IntervalStatus.VALID for interval in result)
    assert result[0].start == START
    assert result[0].end == START + timedelta(minutes=60)
    assert result[0].reason is None
    assert result[0].event_ids == ()
    assert getcontext().prec == 28


def test_empty_and_single_reading_yield_no_intervals_and_consume_events_once():
    calls = 0

    def once() -> Iterator[MeterEvent]:
        nonlocal calls
        calls += 1
        if calls > 1:
            raise AssertionError("events traversed twice")
        yield event(9, 0)

    assert compute_intervals(order_readings([]), once()) == ()
    assert calls == 1
    assert calculate([reading(1, 0, "1")]) == ()


def test_rejects_conflict_even_when_voided_or_flagged():
    for status in (ReadingStatus.VOIDED, ReadingStatus.FLAGGED):
        result = order_readings([reading(1, 0, "1"), reading(2, 0, "1", status=status)])
        with pytest.raises(ValueError, match="conflicts"):
            compute_intervals(result, ())


def test_rejects_forged_hidden_conflict_and_unordered_input():
    first = reading(1, 0, "1")
    same_time = reading(2, 0, "2")
    later = reading(3, 60, "3")
    with pytest.raises(ValueError, match="timestamp conflict"):
        compute_intervals(ReadingOrderResult((first, same_time), ()), ())
    with pytest.raises(ValueError, match="chronological"):
        compute_intervals(ReadingOrderResult((later, first), ()), ())


def test_rejects_malformed_order_input_and_mixed_meters():
    first = reading(1, 0, "1")
    with pytest.raises(TypeError, match="ReadingOrderResult"):
        compute_intervals(None, ())  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="ordered readings"):
        compute_intervals(ReadingOrderResult([first], ()), ())  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="reading at index 1"):
        compute_intervals(ReadingOrderResult((first, None), ()), ())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="different meter"):
        compute_intervals(
            ReadingOrderResult((first, reading(2, 60, "2", meter_id=OTHER_METER)), ()),
            (),
        )


def test_reset_inside_pair_blocks_usage_and_later_pair_computes():
    result = calculate(
        [reading(1, 0, "100"), reading(2, 60, "5"), reading(3, 120, "12")],
        [event(9, 30)],
    )
    assert tuple(interval.status for interval in result) == (
        IntervalStatus.INVALID,
        IntervalStatus.VALID,
    )
    assert result[0].reason is IntervalReason.METER_BOUNDARY
    assert result[0].event_ids == (UUID(int=9),)
    assert result[0].consumption_kwh is None
    assert result[1].consumption_kwh == Decimal(7)


def test_replacement_at_current_reading_belongs_to_new_segment():
    result = calculate(
        [reading(1, 0, "100"), reading(2, 60, "2"), reading(3, 120, "8")],
        [event(9, 60, MeterEventType.REPLACED)],
    )
    assert result[0].reason is IntervalReason.METER_BOUNDARY
    assert result[1].status is IntervalStatus.VALID
    assert result[1].consumption_kwh == Decimal(6)


# covers: AC-3, AC-5
def test_approved_installation_blocks_the_pair_and_keeps_boundary_evidence():
    previous = reading(1, 0, "10")
    current = reading(2, 60, "11")
    installation = event(9, 30, MeterEventType.INSTALLED)

    (interval,) = calculate([previous, current], [installation])

    assert interval.meter_id == METER
    assert interval.previous_reading_id == previous.id
    assert interval.current_reading_id == current.id
    assert interval.start == previous.recorded_at
    assert interval.end == current.recorded_at
    assert interval.status is IntervalStatus.INVALID
    assert interval.reason is IntervalReason.METER_BOUNDARY
    assert interval.event_ids == (installation.id,)
    assert interval.consumption_kwh is None


def test_event_at_previous_reading_or_outside_pairs_does_not_block():
    result = calculate(
        [reading(1, 0, "1"), reading(2, 60, "3")],
        [event(9, -10), event(10, 0), event(11, 120)],
    )
    assert result[0].consumption_kwh == Decimal(2)
    assert result[0].event_ids == ()


def test_multiple_events_have_stable_order_and_unapproved_reason_priority():
    result = calculate(
        [reading(1, 0, "10"), reading(2, 60, "2")],
        [
            event(9, 30, MeterEventType.ROLLOVER),
            event(10, 20, approved=False),
            event(11, 30, MeterEventType.REPLACED),
        ],
    )
    assert result[0].reason is IntervalReason.UNAPPROVED_EVENT
    assert result[0].event_ids == (UUID(int=10), UUID(int=9), UUID(int=11))


@pytest.mark.parametrize("kind", [MeterEventType.ROLLOVER, MeterEventType.CALIBRATION])
def test_approved_unsupported_event_blocks_usage(kind: MeterEventType):
    result = calculate(
        [reading(1, 0, "10"), reading(2, 60, "12")],
        [event(9, 30, kind)],
    )
    assert result[0].reason is IntervalReason.UNSUPPORTED_EVENT
    assert result[0].consumption_kwh is None


def test_unsupported_reason_takes_priority_over_approved_boundary():
    result = calculate(
        [reading(1, 0, "10"), reading(2, 60, "12")],
        [event(9, 30, MeterEventType.RESET), event(10, 40, MeterEventType.ROLLOVER)],
    )
    assert result[0].reason is IntervalReason.UNSUPPORTED_EVENT
    assert result[0].event_ids == (UUID(int=9), UUID(int=10))


def test_flagged_reading_is_a_barrier_not_a_baseline_for_usage():
    result = calculate(
        [
            reading(1, 0, "10"),
            reading(2, 60, "20", status=ReadingStatus.FLAGGED),
            reading(3, 120, "30"),
            reading(4, 180, "35"),
        ]
    )
    assert tuple(interval.reason for interval in result) == (
        IntervalReason.FLAGGED_READING,
        IntervalReason.FLAGGED_READING,
        None,
    )
    assert result[2].consumption_kwh == Decimal(5)


# covers: AC-4, AC-5
def test_flagged_decrease_keeps_the_status_reason_and_no_numeric_usage():
    result = calculate(
        [reading(1, 0, "100"), reading(2, 60, "5", status=ReadingStatus.FLAGGED)]
    )

    assert len(result) == 1
    assert result[0].reason is IntervalReason.FLAGGED_READING
    assert result[0].consumption_kwh is None


def test_voided_reading_is_excluded_and_valid_pair_spans_it():
    readings = [
        reading(1, 0, "10"),
        reading(2, 60, "99", status=ReadingStatus.VOIDED),
        reading(3, 120, "15"),
    ]
    result = calculate(readings)
    assert len(result) == 1
    assert result[0].previous_reading_id == readings[0].id
    assert result[0].current_reading_id == readings[2].id
    assert result[0].consumption_kwh == Decimal(5)
    assert readings[1].status is ReadingStatus.VOIDED


def test_event_between_readings_still_blocks_when_voided_reading_is_between():
    result = calculate(
        [
            reading(1, 0, "10"),
            reading(2, 60, "99", status=ReadingStatus.VOIDED),
            reading(3, 120, "15"),
        ],
        [event(9, 60)],
    )
    assert result[0].reason is IntervalReason.METER_BOUNDARY


def test_unexplained_decrease_is_invalid_and_lower_value_can_start_later_pair():
    result = calculate(
        [reading(1, 0, "100"), reading(2, 60, "5"), reading(3, 120, "8")]
    )
    assert result[0].reason is IntervalReason.UNEXPLAINED_DECREASE
    assert result[0].consumption_kwh is None
    assert result[1].consumption_kwh == Decimal(3)


def test_event_precedes_flagged_and_decrease_reason():
    result = calculate(
        [reading(1, 0, "100"), reading(2, 60, "5", status=ReadingStatus.FLAGGED)],
        [event(9, 30)],
    )
    assert result[0].reason is IntervalReason.METER_BOUNDARY


def test_event_input_is_validated_before_any_interval_is_returned():
    readings = [reading(1, 0, "1"), reading(2, 60, "2")]
    with pytest.raises(ValueError, match="event at index 1.*different meter"):
        calculate(readings, [event(9, 30), event(10, 40, meter_id=OTHER_METER)])
    with pytest.raises(TypeError, match="event at index 0.*MeterEvent"):
        calculate(readings, [None])


# covers: AC-5
def test_event_input_is_validated_even_when_there_are_no_readings():
    with pytest.raises(TypeError, match="event at index 0.*MeterEvent"):
        compute_intervals(order_readings([]), [None])  # type: ignore[list-item]


def test_events_iterable_is_consumed_once_and_input_order_is_unchanged():
    source = [event(9, 50), event(10, 20)]
    traversals = 0

    def once() -> Iterator[MeterEvent]:
        nonlocal traversals
        traversals += 1
        if traversals > 1:
            raise AssertionError("events traversed twice")
        yield from source

    result = calculate([reading(1, 0, "1"), reading(2, 60, "2")], once())
    assert traversals == 1
    assert source[0].effective_at > source[1].effective_at
    assert result[0].event_ids == (UUID(int=10), UUID(int=9))


def test_interval_record_rejects_inconsistent_values_and_is_immutable():
    common: dict[str, Any] = {
        "meter_id": METER,
        "previous_reading_id": UUID(int=1),
        "current_reading_id": UUID(int=2),
        "start": START,
        "end": START + timedelta(minutes=60),
    }
    valid = ConsumptionInterval(
        **common, status=IntervalStatus.VALID, consumption_kwh=Decimal(0)
    )
    with pytest.raises(FrozenInstanceError):
        valid.consumption_kwh = Decimal(1)  # pyright: ignore[reportAttributeAccessIssue]
    zero_length: dict[str, Any] = {**common, "end": START}
    with pytest.raises(ValueError, match="end must be after start"):
        ConsumptionInterval(
            **zero_length,
            status=IntervalStatus.VALID,
            consumption_kwh=Decimal(1),
        )
    with pytest.raises(ValueError, match="cannot have consumption_kwh"):
        ConsumptionInterval(
            **common,
            status=IntervalStatus.INVALID,
            reason=IntervalReason.UNEXPLAINED_DECREASE,
            consumption_kwh=Decimal(1),
        )
    with pytest.raises(ValueError, match="requires event_ids"):
        ConsumptionInterval(
            **common,
            status=IntervalStatus.INVALID,
            reason=IntervalReason.METER_BOUNDARY,
        )
