from collections.abc import Iterator
from dataclasses import fields, is_dataclass
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal, DecimalException
from typing import Any
from uuid import UUID

import pytest

from energyiq.readings import (
    ConsumptionGap,
    ConsumptionInterval,
    ConsumptionWindowSummary,
    GapReason,
    IntervalReason,
    IntervalStatus,
    MeterEvent,
    MeterEventType,
    NormalizedInterval,
    Reading,
    ReadingSource,
    ReadingStatus,
    compute_intervals,
    normalize_intervals,
    order_readings,
    summarize_consumption,
)

METER = UUID(int=100)
OTHER_METER = UUID(int=200)
ACTOR = UUID(int=300)
START = datetime(2026, 11, 3, 12, tzinfo=UTC)


def at(hours: float) -> datetime:
    return START + timedelta(hours=hours)


def valid(
    number: int,
    start: float,
    end: float,
    kwh: str,
    *,
    meter_id: UUID = METER,
) -> ConsumptionInterval:
    return ConsumptionInterval(
        meter_id=meter_id,
        previous_reading_id=UUID(int=number),
        current_reading_id=UUID(int=number + 1),
        start=at(start),
        end=at(end),
        status=IntervalStatus.VALID,
        consumption_kwh=Decimal(kwh),
    )


def invalid(
    number: int,
    start: float,
    end: float,
    reason: IntervalReason = IntervalReason.FLAGGED_READING,
    event_ids: tuple[UUID, ...] = (),
) -> ConsumptionInterval:
    return ConsumptionInterval(
        meter_id=METER,
        previous_reading_id=UUID(int=number),
        current_reading_id=UUID(int=number + 1),
        start=at(start),
        end=at(end),
        status=IntervalStatus.INVALID,
        event_ids=event_ids,
        reason=reason,
    )


def every_36_hours(count: int) -> list[ConsumptionInterval]:
    return [valid(n, n * 36, (n + 1) * 36, "10") for n in range(count)]


def summarize(
    intervals: list[ConsumptionInterval], start: float, end: float
) -> ConsumptionWindowSummary:
    return summarize_consumption(intervals, METER, at(start), at(end))


def assert_tiles(summary: ConsumptionWindowSummary) -> None:
    spans = sorted(
        [(m.interval.start, m.interval.end) for m in summary.measured_intervals]
        + [(g.start, g.end) for g in summary.gaps]
    )
    cursor = summary.window_start
    for span_start, span_end in spans:
        assert span_start == cursor, "hole or overlap in the window tiling"
        assert span_end > span_start
        cursor = span_end
    assert cursor == summary.window_end
    starts = [g.start for g in summary.gaps]
    assert starts == sorted(starts)
    measured_starts = [m.interval.start for m in summary.measured_intervals]
    assert measured_starts == sorted(measured_starts)
    assert summary.covered == sum(
        (m.duration for m in summary.measured_intervals), timedelta(0)
    )
    assert summary.uncovered == sum((g.duration for g in summary.gaps), timedelta(0))
    assert summary.covered + summary.uncovered == (
        summary.window_end - summary.window_start
    )


def assert_no_float(value: Any) -> None:
    assert not isinstance(value, float)
    if is_dataclass(value) and not isinstance(value, type):
        for field in fields(value):
            assert_no_float(getattr(value, field.name))
    elif isinstance(value, tuple):
        for item in value:  # pyright: ignore[reportUnknownVariableType]
            assert_no_float(item)


# AC-1: per interval rates


def test_rates_use_real_elapsed_time_and_round_once():
    result = normalize_intervals(every_36_hours(3))

    assert len(result) == 3
    for item in result:
        assert item.duration == timedelta(hours=36)
        assert item.kwh_per_day == Decimal("6.666667")
        assert item.kwh_per_day.as_tuple().exponent == -6  # pyright: ignore[reportOptionalMemberAccess]


def test_rates_keep_input_order_and_wrap_the_input_record():
    chain = [valid(1, 0, 20, "5"), valid(2, 20, 236, "90")]
    result = normalize_intervals(chain)

    assert [item.interval for item in result] == chain
    assert result[0].kwh_per_day == Decimal("6.000000")
    assert result[1].kwh_per_day == Decimal("10.000000")


@pytest.mark.parametrize(
    ("kwh", "expected"),
    [
        ("0.0000005", "0.000000"),
        ("0.0000015", "0.000002"),
        ("0.0000025", "0.000002"),
        ("0.0000035", "0.000004"),
        ("0.00000050001", "0.000001"),
    ],
)
def test_rate_halfway_cases_round_half_even(kwh: str, expected: str):
    (item,) = normalize_intervals([valid(1, 0, 24, kwh)])
    assert item.kwh_per_day == Decimal(expected)
    assert str(item.kwh_per_day) == expected


def test_sub_second_durations_use_exact_microseconds():
    interval = ConsumptionInterval(
        meter_id=METER,
        previous_reading_id=UUID(int=1),
        current_reading_id=UUID(int=2),
        start=START,
        end=START + timedelta(microseconds=1),
        status=IntervalStatus.VALID,
        consumption_kwh=Decimal("0.000001"),
    )
    (item,) = normalize_intervals([interval])
    assert item.kwh_per_day == Decimal("86400.000000")


def test_zero_usage_has_zero_rate_and_counts_as_measured():
    chain = [valid(1, 0, 24, "0")]
    (item,) = normalize_intervals(chain)
    assert item.kwh_per_day == Decimal("0.000000")
    assert str(item.kwh_per_day) == "0.000000"

    summary = summarize(chain, 0, 24)
    assert summary.gaps == ()
    assert summary.covered == timedelta(hours=24)
    assert summary.coverage_ratio == Decimal("1.0000")
    assert summary.average_kwh_per_day == Decimal("0.000000")
    assert_tiles(summary)


def test_invalid_interval_has_no_rate():
    (item,) = normalize_intervals([invalid(1, 0, 10)])
    assert item.kwh_per_day is None
    assert item.duration == timedelta(hours=10)


def test_empty_input_returns_empty_tuple():
    assert normalize_intervals([]) == ()


# AC-2: chain validation, for both functions


def _call_both(chain: list[Any]) -> list[Exception]:
    errors: list[Exception] = []
    for call in (
        lambda: normalize_intervals(chain),
        lambda: summarize_consumption(chain, METER, at(0), at(100)),
    ):
        with pytest.raises(Exception) as caught:
            call()
        errors.append(caught.value)
    return errors


def test_wrong_item_type_raises_indexed_type_error():
    for error in _call_both([valid(1, 0, 10, "1"), "nope"]):
        assert isinstance(error, TypeError)
        assert "index 1" in str(error)


def test_hole_raises_indexed_value_error():
    chain = every_36_hours(3)
    del chain[1]
    for error in _call_both(chain):
        assert isinstance(error, ValueError)
        assert "index 1" in str(error) and "hole" in str(error)


def test_overlap_raises_indexed_value_error():
    chain = [valid(1, 0, 10, "1"), valid(2, 5, 20, "1")]
    for error in _call_both(chain):
        assert isinstance(error, ValueError)
        assert "index 1" in str(error) and "overlaps" in str(error)


def test_mixed_meters_raise_indexed_value_error():
    chain = [valid(1, 0, 10, "1"), valid(2, 10, 20, "1", meter_id=OTHER_METER)]
    for error in _call_both(chain):
        assert isinstance(error, ValueError)
        assert "index 1" in str(error) and "different meter" in str(error)


def test_single_pass_iterator_is_consumed_once():
    chain = every_36_hours(3)

    def once() -> Iterator[ConsumptionInterval]:
        yield from chain

    assert len(normalize_intervals(once())) == 3
    summary = summarize_consumption(once(), METER, at(0), at(108))
    assert summary.measured_kwh == Decimal(30)


def test_input_records_are_not_modified():
    chain = every_36_hours(2) + [invalid(9, 72, 80)]
    snapshot = list(chain)
    normalize_intervals(chain)
    summarize(chain, -1, 90)
    assert chain == snapshot


# AC-3: summary argument validation


def test_non_uuid_meter_id_raises_type_error():
    with pytest.raises(TypeError, match="meter_id must be a UUID"):
        summarize_consumption([], "meter", at(0), at(1))  # type: ignore[arg-type]


def test_meter_mismatch_raises_indexed_value_error():
    chain = [valid(1, 0, 10, "1")]
    with pytest.raises(ValueError, match="index 0 belongs to a different meter"):
        summarize_consumption(chain, OTHER_METER, at(0), at(10))


@pytest.mark.parametrize(
    ("start", "end", "error", "message"),
    [
        (START.replace(tzinfo=None), at(1), ValueError, "window_start must include"),
        (START, at(1).replace(tzinfo=None), ValueError, "window_end must include"),
        (
            START.astimezone(timezone(timedelta(hours=-4))),
            at(1),
            ValueError,
            "window_start must have a zero UTC offset",
        ),
        ("2026-11-03", at(1), TypeError, "window_start must be a datetime"),
        (at(1), at(1), ValueError, "window_end must be after window_start"),
        (at(2), at(1), ValueError, "window_end must be after window_start"),
    ],
)
def test_bad_window_bounds_raise(
    start: Any, end: Any, error: type[Exception], message: str
):
    with pytest.raises(error, match=message):
        summarize_consumption([], METER, start, end)


# AC-4, AC-5, AC-7: measured path


def test_happy_path_full_window():
    summary = summarize(every_36_hours(3), 0, 108)

    assert summary.measured_kwh == Decimal(30)
    assert [m.kwh_per_day for m in summary.measured_intervals] == [
        Decimal("6.666667")
    ] * 3
    assert summary.coverage_ratio == Decimal("1.0000")
    assert str(summary.coverage_ratio) == "1.0000"
    assert summary.average_kwh_per_day == Decimal("6.666667")
    assert summary.gaps == ()
    assert summary.uncovered == timedelta(0)
    assert summary.meter_id == METER
    assert_tiles(summary)


def test_bound_touching_intervals_do_not_overlap_the_window():
    chain = [valid(1, 0, 10, "4"), valid(2, 10, 20, "6"), valid(3, 20, 30, "8")]
    summary = summarize(chain, 10, 20)

    assert [m.interval for m in summary.measured_intervals] == [chain[1]]
    assert summary.measured_kwh == Decimal(6)
    assert summary.gaps == ()
    assert summary.coverage_ratio == Decimal("1.0000")
    assert_tiles(summary)


def test_no_measured_intervals_gives_zero_decimal_and_empty_tuple():
    summary = summarize([valid(1, 0, 10, "4")], 2, 8)

    assert summary.measured_kwh == Decimal(0)
    assert summary.measured_intervals == ()
    assert summary.covered == timedelta(0)
    assert summary.average_kwh_per_day is None
    assert [g.reason for g in summary.gaps] == [GapReason.PARTIAL_INTERVAL]
    assert_tiles(summary)


@pytest.mark.parametrize(
    ("covered_hours", "window_hours", "expected"),
    [(1, 3, "0.3333"), (2, 3, "0.6667"), (3, 3, "1.0000")],
)
def test_coverage_ratio_rounds_once_to_four_places(
    covered_hours: int, window_hours: int, expected: str
):
    chain = [valid(1, 0, covered_hours, "1"), invalid(2, covered_hours, 10)]
    summary = summarize(chain, 0, window_hours)
    assert summary.coverage_ratio == Decimal(expected)
    assert str(summary.coverage_ratio) == expected
    assert_tiles(summary)


@pytest.mark.parametrize(
    ("covered_seconds", "expected"), [(1, "0.0000"), (3, "0.0002"), (5, "0.0002")]
)
def test_coverage_ratio_halfway_cases_round_half_even(
    covered_seconds: int, expected: str
):
    # covered / 20,000 s puts the tie at the fifth decimal: 0.00005, 0.00015, 0.00025
    split = START + timedelta(seconds=covered_seconds)
    chain = [
        ConsumptionInterval(
            meter_id=METER,
            previous_reading_id=UUID(int=1),
            current_reading_id=UUID(int=2),
            start=START,
            end=split,
            status=IntervalStatus.VALID,
            consumption_kwh=Decimal(1),
        ),
        ConsumptionInterval(
            meter_id=METER,
            previous_reading_id=UUID(int=2),
            current_reading_id=UUID(int=3),
            start=split,
            end=at(10),
            status=IntervalStatus.INVALID,
            reason=IntervalReason.FLAGGED_READING,
        ),
    ]
    summary = summarize_consumption(
        chain, METER, START, START + timedelta(seconds=20_000)
    )
    assert summary.coverage_ratio == Decimal(expected)


def test_average_is_over_covered_time_not_window_time():
    chain = [valid(1, 0, 12, "3"), valid(2, 12, 24, "5"), invalid(3, 24, 48)]
    summary = summarize(chain, 0, 48)

    assert summary.measured_kwh == Decimal(8)
    assert summary.covered == timedelta(hours=24)
    assert summary.coverage_ratio == Decimal("0.5000")
    assert summary.average_kwh_per_day == Decimal("8.000000")
    assert_tiles(summary)


def test_measured_kwh_sum_is_exact_and_independent_of_caller_context():
    from decimal import localcontext

    chain = [valid(1, 0, 1, "0.1"), valid(2, 1, 2, "0.2"), valid(3, 2, 3, "1234.5678")]
    with localcontext() as context:
        context.prec = 2
        summary = summarize(chain, 0, 3)
    assert summary.measured_kwh == Decimal("1234.8678")


def test_measured_kwh_that_cannot_be_held_exactly_raises():
    chain = [
        valid(1, 0, 1, "1" + "0" * 27),
        valid(2, 1, 2, "0.1"),
    ]
    with pytest.raises(DecimalException):
        summarize(chain, 0, 2)


# AC-5, AC-6, AC-8: gap characterization


def _reading(number: int, hours: float, value: str, status: ReadingStatus) -> Reading:
    return Reading(
        id=UUID(int=number),
        meter_id=METER,
        recorded_at=at(hours),
        cumulative_kwh=Decimal(value),
        source=ReadingSource.MANUAL,
        status=status,
        created_at=START,
    )


def test_mixed_gaps_from_real_interval_chain():
    flagged = ReadingStatus.FLAGGED
    ok = ReadingStatus.VALID
    readings = [
        _reading(1, 0, "100", ok),
        _reading(2, 10, "110", ok),
        _reading(3, 20, "5", ok),  # after the reset
        _reading(4, 30, "15", flagged),
        _reading(5, 40, "25", ok),
        _reading(6, 50, "35", ok),
    ]
    reset = MeterEvent(
        id=UUID(int=900),
        meter_id=METER,
        event_type=MeterEventType.RESET,
        effective_at=at(15),
        created_at=START,
        approved_by=ACTOR,
        approved_at=START,
    )
    chain = compute_intervals(order_readings(readings), [reset])

    summary = summarize_consumption(chain, METER, at(-5), at(45))

    assert [m.interval for m in summary.measured_intervals] == [chain[0]]
    assert summary.measured_kwh == Decimal(10)
    assert [(g.reason, g.start, g.end) for g in summary.gaps] == [
        (GapReason.BEFORE_FIRST_READING, at(-5), at(0)),
        (GapReason.INVALID_INTERVAL, at(10), at(20)),
        (GapReason.INVALID_INTERVAL, at(20), at(30)),
        (GapReason.INVALID_INTERVAL, at(30), at(40)),
        (GapReason.PARTIAL_INTERVAL, at(40), at(45)),
    ]
    before, boundary, flagged_a, flagged_b, partial = summary.gaps

    assert before.previous_reading_id is None and before.event_ids == ()
    assert before.interval_reason is None
    assert boundary.interval_reason is IntervalReason.METER_BOUNDARY
    assert boundary.event_ids == (UUID(int=900),)
    assert (boundary.previous_reading_id, boundary.current_reading_id) == (
        UUID(int=2),
        UUID(int=3),
    )
    assert flagged_a.interval_reason is IntervalReason.FLAGGED_READING
    assert flagged_b.interval_reason is IntervalReason.FLAGGED_READING
    assert flagged_a.event_ids == ()
    assert partial.interval_reason is None
    assert partial.event_ids == ()
    assert (partial.previous_reading_id, partial.current_reading_id) == (
        UUID(int=5),
        UUID(int=6),
    )
    assert partial.duration == timedelta(hours=5)
    # The partial interval's 10 kWh never reaches the total or the average.
    assert summary.average_kwh_per_day == Decimal("24.000000")
    assert summary.coverage_ratio == Decimal("0.2000")
    assert_tiles(summary)
    assert_no_float(summary)


def test_invalid_interval_crossing_a_bound_stays_invalid_and_is_trimmed():
    event_id = UUID(int=77)
    chain = [
        invalid(1, 0, 10, IntervalReason.UNAPPROVED_EVENT, (event_id,)),
        valid(2, 10, 20, "5"),
    ]
    summary = summarize(chain, 4, 20)

    (gap,) = summary.gaps
    assert gap.reason is GapReason.INVALID_INTERVAL
    assert gap.interval_reason is IntervalReason.UNAPPROVED_EVENT
    assert gap.event_ids == (event_id,)
    assert (gap.start, gap.end) == (at(4), at(10))
    assert summary.measured_kwh == Decimal(5)
    assert_tiles(summary)


def test_window_inside_one_valid_interval_is_one_partial_gap():
    summary = summarize([valid(1, 0, 100, "50")], 10, 20)
    (gap,) = summary.gaps
    assert gap.reason is GapReason.PARTIAL_INTERVAL
    assert (gap.start, gap.end) == (at(10), at(20))
    assert summary.measured_kwh == Decimal(0)
    assert_tiles(summary)


def test_after_last_reading_gap_is_trimmed():
    summary = summarize(every_36_hours(1), 0, 50)
    assert [(g.reason, g.start, g.end) for g in summary.gaps] == [
        (GapReason.AFTER_LAST_READING, at(36), at(50))
    ]
    assert summary.coverage_ratio == Decimal("0.7200")
    assert_tiles(summary)


@pytest.mark.parametrize(
    ("chain", "start", "end", "reason"),
    [
        ([], 0, 24, GapReason.NO_INTERVALS),
        (every_36_hours(2), -48, -1, GapReason.BEFORE_FIRST_READING),
        (every_36_hours(2), -48, 0, GapReason.BEFORE_FIRST_READING),
        (every_36_hours(2), 72, 100, GapReason.AFTER_LAST_READING),
        (every_36_hours(2), 200, 300, GapReason.AFTER_LAST_READING),
    ],
)
def test_no_data_returns_one_whole_window_gap(
    chain: list[ConsumptionInterval], start: float, end: float, reason: GapReason
):
    summary = summarize(chain, start, end)

    assert summary.measured_kwh == Decimal(0)
    assert summary.measured_intervals == ()
    assert summary.covered == timedelta(0)
    assert summary.coverage_ratio == Decimal("0.0000")
    assert summary.average_kwh_per_day is None
    (gap,) = summary.gaps
    assert gap.reason is reason
    assert (gap.start, gap.end) == (at(start), at(end))
    assert gap.previous_reading_id is None
    assert_tiles(summary)
    assert_no_float(summary)


# Record field rules


def test_normalized_interval_rejects_inconsistent_fields():
    interval = valid(1, 0, 24, "1")
    with pytest.raises(ValueError, match="duration"):
        NormalizedInterval(interval, timedelta(hours=1), Decimal("1.000000"))
    with pytest.raises(ValueError, match="6 fractional places"):
        NormalizedInterval(interval, timedelta(hours=24), Decimal(1))
    with pytest.raises(ValueError, match="requires kwh_per_day"):
        NormalizedInterval(interval, timedelta(hours=24), None)
    with pytest.raises(ValueError, match="cannot have kwh_per_day"):
        NormalizedInterval(invalid(1, 0, 24), timedelta(hours=24), Decimal("1.000000"))
    with pytest.raises(TypeError, match="must be a Decimal"):
        NormalizedInterval(interval, timedelta(hours=24), 1.0)  # type: ignore[arg-type]


def test_gap_rejects_inconsistent_fields():
    hour = timedelta(hours=1)
    with pytest.raises(ValueError, match="after start"):
        ConsumptionGap(at(1), at(1), timedelta(0), GapReason.NO_INTERVALS)
    with pytest.raises(ValueError, match="duration"):
        ConsumptionGap(at(0), at(1), 2 * hour, GapReason.NO_INTERVALS)
    with pytest.raises(TypeError, match="requires an IntervalReason"):
        ConsumptionGap(
            at(0),
            at(1),
            hour,
            GapReason.INVALID_INTERVAL,
            None,
            UUID(int=1),
            UUID(int=2),
        )
    with pytest.raises(ValueError, match="only an invalid_interval gap"):
        ConsumptionGap(
            at(0),
            at(1),
            hour,
            GapReason.PARTIAL_INTERVAL,
            IntervalReason.FLAGGED_READING,
            UUID(int=1),
            UUID(int=2),
        )
    with pytest.raises(TypeError, match="previous_reading_id must be a UUID"):
        ConsumptionGap(at(0), at(1), hour, GapReason.PARTIAL_INTERVAL)
    with pytest.raises(ValueError, match="reading ids"):
        ConsumptionGap(
            at(0), at(1), hour, GapReason.BEFORE_FIRST_READING, None, UUID(int=1)
        )
    with pytest.raises(ValueError, match="event_ids"):
        ConsumptionGap(
            at(0),
            at(1),
            hour,
            GapReason.PARTIAL_INTERVAL,
            None,
            UUID(int=1),
            UUID(int=2),
            (UUID(int=3),),
        )


def test_summary_rejects_inconsistent_fields():
    good: dict[str, Any] = {
        "meter_id": METER,
        "window_start": at(0),
        "window_end": at(1),
        "measured_kwh": Decimal(0),
        "covered": timedelta(0),
        "uncovered": timedelta(hours=1),
        "coverage_ratio": Decimal("0.0000"),
        "average_kwh_per_day": None,
        "measured_intervals": (),
        "gaps": (),
    }
    ConsumptionWindowSummary(**good)
    cases: list[tuple[dict[str, Any], type[Exception]]] = [
        ({"uncovered": timedelta(hours=2)}, ValueError),
        ({"coverage_ratio": Decimal(0)}, ValueError),
        ({"average_kwh_per_day": Decimal("1.000000")}, ValueError),
        ({"measured_kwh": Decimal(-1)}, ValueError),
        ({"measured_intervals": [1]}, TypeError),
        ({"gaps": ("x",)}, TypeError),
        ({"covered": timedelta(hours=1), "uncovered": timedelta(0)}, ValueError),
    ]
    for change, error in cases:
        with pytest.raises(error):
            ConsumptionWindowSummary(**{**good, **change})
