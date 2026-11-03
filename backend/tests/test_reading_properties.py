"""Property based tests for reading order, intervals, window tiling, additivity.

Spec 0006 (P1-05). The strategies build real ``Reading`` and ``MeterEvent``
records and push them through the real ``order_readings``,
``compute_intervals`` and ``summarize_consumption`` pipeline. Expected values
are derived from the generated inputs and the rules of specs 0003 to 0005.
There is no second implementation of the code under test, no private
``energyiq`` function is called, and no expected value is a binary float.

Times are built as small steps on a coarse grid from a fixed UTC base, so
collisions, 1 microsecond intervals, events on reading instants, and window
bounds on (or 1 microsecond from) interval boundaries come up regularly.
Every strategy builds valid records directly, with no ``assume`` or
``filter``, so no health check needs suppressing.
"""

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, fields, is_dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext
from fractions import Fraction
from itertools import accumulate, pairwise
from typing import cast
from uuid import UUID

import pytest
from hypothesis import given
from hypothesis import strategies as st

from energyiq.consumption import exact_kwh_context
from energyiq.readings import (
    ConsumptionInterval,
    ConsumptionWindowSummary,
    GapReason,
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
    summarize_consumption,
)

BASE = datetime(2026, 1, 1, tzinfo=UTC)
ACTOR = UUID(int=900)
EVENT_ID_OFFSET = 10_000
ONE_US = timedelta(microseconds=1)
MAX_KWH = Decimal("999999999999.999999")
MAX_WHOLE_KWH = 999_999_999_999
MAX_FRACTIONAL_PLACES = 6
MAX_ARBITRARY_STEP_US = 60 * 86_400 * 1_000_000
WINDOW_MARGIN = timedelta(days=30)
RATIO_PLACES = 4
RATE_PLACES = 6
MICROSECONDS_PER_DAY = 86_400_000_000

FIXED_STEPS = (
    ONE_US,
    timedelta(seconds=1),
    timedelta(hours=1),
    timedelta(days=1),
    timedelta(hours=36),
)
# Weighted toward valid; sampled_from shrinks toward the first entry.
CHAIN_STATUSES = (
    ReadingStatus.VALID,
    ReadingStatus.VALID,
    ReadingStatus.VALID,
    ReadingStatus.VALID,
    ReadingStatus.FLAGGED,
    ReadingStatus.VOIDED,
)
UNSUPPORTED_TYPES = (MeterEventType.ROLLOVER, MeterEventType.CALIBRATION)

type IntervalKey = tuple[UUID, UUID]


# --------------------------------------------------------------------------
# Strategies
# --------------------------------------------------------------------------


def positive_steps() -> st.SearchStrategy[timedelta]:
    """A nonzero time step: a grid step or arbitrary microseconds."""
    return st.one_of(
        st.sampled_from(FIXED_STEPS),
        st.integers(1, MAX_ARBITRARY_STEP_US).map(
            lambda us: timedelta(microseconds=us)
        ),
    )


def steps() -> st.SearchStrategy[timedelta]:
    """A time step where zero (a timestamp collision) is common."""
    return st.one_of(st.just(timedelta(0)), positive_steps())


@st.composite
def kwh_values(draw: st.DrawFn) -> Decimal:
    """Any validated cumulative kWh: 0 to the maximum, 0 to 6 places."""
    places = draw(st.integers(0, MAX_FRACTIONAL_PLACES))
    scaled = draw(st.integers(0, (MAX_WHOLE_KWH + 1) * 10**places - 1))
    return Decimal(f"{scaled}e-{places}")


@st.composite
def kwh_increments(draw: st.DrawFn) -> Decimal:
    """A small nonnegative kWh step with 0 to 6 places."""
    places = draw(st.integers(0, MAX_FRACTIONAL_PLACES))
    scaled = draw(st.integers(0, 10 ** (places + 4)))
    return Decimal(f"{scaled}e-{places}")


def make_reading(
    index: int,
    meter_id: UUID,
    recorded_at: datetime,
    kwh: Decimal,
    status: ReadingStatus,
    source: ReadingSource = ReadingSource.MANUAL,
) -> Reading:
    return Reading(
        id=UUID(int=index + 1),
        meter_id=meter_id,
        recorded_at=recorded_at,
        cumulative_kwh=kwh,
        source=source,
        status=status,
        created_at=BASE,
    )


@st.composite
def reading_lists(draw: st.DrawFn) -> list[Reading]:
    """0 to 30 readings for one meter, any status, shuffled, with collisions.

    A few occurrences repeat the same reading object, so an exact duplicate
    occurrence is also tested.
    """
    meter_id = draw(st.uuids())
    offsets = list(accumulate(draw(st.lists(steps(), max_size=28))))
    readings = [
        make_reading(
            index,
            meter_id,
            BASE + offset,
            draw(kwh_values()),
            draw(st.sampled_from(ReadingStatus)),
            draw(st.sampled_from(ReadingSource)),
        )
        for index, offset in enumerate(offsets)
    ]
    repeats = draw(st.lists(st.sampled_from(readings), max_size=2)) if readings else []
    return list(draw(st.permutations(readings + repeats)))


@st.composite
def chain_values(draw: st.DrawFn, count: int) -> list[Decimal]:
    """Cumulative values, mostly nondecreasing, with occasional decreases."""
    values: list[Decimal] = []
    for _ in range(count):
        if not values:
            values.append(draw(kwh_values()))
            continue
        move = draw(st.sampled_from(("up", "up", "up", "same", "jump")))
        previous = values[-1]
        if move == "up":
            with localcontext(exact_kwh_context()):
                values.append(min(previous + draw(kwh_increments()), MAX_KWH))
        elif move == "same":
            values.append(previous)
        else:
            values.append(draw(kwh_values()))
    return values


@st.composite
def reading_chains(draw: st.DrawFn, meter_id: UUID) -> ReadingOrderResult:
    """0 to 30 readings with strictly increasing times (no conflicts)."""
    count = draw(st.integers(0, 30))
    first = draw(steps())
    gaps = draw(st.lists(positive_steps(), min_size=max(0, count - 1), max_size=29))
    offsets = list(accumulate([first, *gaps[: max(0, count - 1)]]))[:count]
    values = draw(chain_values(count))
    readings = [
        make_reading(
            index,
            meter_id,
            BASE + offset,
            value,
            draw(st.sampled_from(CHAIN_STATUSES)),
        )
        for index, (offset, value) in enumerate(zip(offsets, values, strict=True))
    ]
    result = order_readings(readings)
    assert not result.conflicts
    return result


@st.composite
def event_instants(draw: st.DrawFn, times: Sequence[datetime]) -> datetime:
    """On a reading instant, 1 us from one, between two, or outside the data."""
    if not times:
        return BASE + draw(steps())
    choice = draw(
        st.sampled_from(("on", "minus", "plus", "between", "before", "after"))
    )
    anchor = draw(st.sampled_from(times))
    if choice == "on":
        return anchor
    if choice == "minus":
        return anchor - ONE_US
    if choice == "plus":
        return anchor + ONE_US
    if choice == "between" and len(times) > 1:
        index = draw(st.integers(0, len(times) - 2))
        span = (times[index + 1] - times[index]) // ONE_US
        return times[index] + timedelta(microseconds=draw(st.integers(0, span)))
    if choice == "before":
        return times[0] - draw(positive_steps())
    return times[-1] + draw(positive_steps())


@st.composite
def event_lists(
    draw: st.DrawFn, meter_id: UUID, times: Sequence[datetime]
) -> tuple[MeterEvent, ...]:
    """0 to 6 events of any type, approved or not, near the reading instants."""
    count = draw(st.integers(0, 6))
    events: list[MeterEvent] = []
    for index in range(count):
        approved = draw(st.booleans())
        events.append(
            MeterEvent(
                id=UUID(int=EVENT_ID_OFFSET + index),
                meter_id=meter_id,
                event_type=draw(st.sampled_from(MeterEventType)),
                effective_at=draw(event_instants(times)),
                created_at=BASE,
                approved_by=ACTOR if approved else None,
                approved_at=BASE if approved else None,
            )
        )
    return tuple(events)


@dataclass(frozen=True, slots=True)
class Scenario:
    meter_id: UUID
    order: ReadingOrderResult
    events: tuple[MeterEvent, ...]

    @property
    def intervals(self) -> tuple[ConsumptionInterval, ...]:
        return compute_intervals(self.order, self.events)


@st.composite
def scenarios(draw: st.DrawFn) -> Scenario:
    meter_id = draw(st.uuids())
    order = draw(reading_chains(meter_id))
    times = [reading.recorded_at for reading in order.ordered]
    return Scenario(meter_id, order, draw(event_lists(meter_id, times)))


def boundary_points(scenario: Scenario) -> list[datetime]:
    """Interval boundaries, or reading times when there are no intervals."""
    intervals = scenario.intervals
    if intervals:
        return [interval.start for interval in intervals] + [intervals[-1].end]
    return [reading.recorded_at for reading in scenario.order.ordered] or [BASE]


def anchor_points(boundaries: Sequence[datetime]) -> list[datetime]:
    """Boundaries, 1 us either side of each, and instants far outside the data."""
    points = [
        point
        for boundary in boundaries
        for point in (boundary - ONE_US, boundary, boundary + ONE_US)
    ]
    points += [boundaries[0] - WINDOW_MARGIN, boundaries[-1] + WINDOW_MARGIN]
    return sorted(set(points))


@st.composite
def window_points(draw: st.DrawFn, scenario: Scenario) -> datetime:
    """An anchor, or an arbitrary instant within, before, or after the data.

    Hypothesis favors small integers, so arbitrary offsets are measured from
    both ends of the range. Otherwise windows after the data would be rare.
    Exact boundaries get their own branch, so a window bound often sits
    exactly on a valid interval's start or end.
    """
    boundaries = boundary_points(scenario)
    anchors = anchor_points(boundaries)
    low = anchors[0] - WINDOW_MARGIN
    high = anchors[-1] + WINDOW_MARGIN
    span = (high - low) // ONE_US
    return draw(
        st.one_of(
            st.sampled_from(boundaries),
            st.sampled_from(anchors),
            st.integers(0, span).map(lambda us: low + timedelta(microseconds=us)),
            st.integers(0, span).map(lambda us: high - timedelta(microseconds=us)),
        )
    )


@st.composite
def windows(draw: st.DrawFn, scenario: Scenario) -> tuple[datetime, datetime]:
    """A window with ``end > start`` by construction, no filtering."""
    start, end = sorted((draw(window_points(scenario)), draw(window_points(scenario))))
    if end == start:
        end = start + draw(positive_steps())
    return start, end


@st.composite
def cut_points(draw: st.DrawFn, scenario: Scenario) -> tuple[datetime, ...]:
    """3 to 6 strictly increasing instants (k = 2 to 5 adjacent windows)."""
    count = draw(st.integers(3, 6))
    points = sorted(draw(window_points(scenario)) for _ in range(count))
    for index in range(1, count):
        if points[index] <= points[index - 1]:
            points[index] = points[index - 1] + draw(positive_steps())
    return tuple(points)


@st.composite
def window_cases(draw: st.DrawFn) -> tuple[Scenario, tuple[datetime, datetime]]:
    scenario = draw(scenarios())
    return scenario, draw(windows(scenario))


@st.composite
def cut_cases(draw: st.DrawFn) -> tuple[Scenario, tuple[datetime, ...]]:
    scenario = draw(scenarios())
    return scenario, draw(cut_points(scenario))


@st.composite
def shuffled_chains(draw: st.DrawFn) -> tuple[ReadingOrderResult, list[Reading]]:
    order = draw(reading_chains(draw(st.uuids())))
    return order, list(draw(st.permutations(order.ordered)))


@st.composite
def colliding_lists(draw: st.DrawFn) -> list[Reading]:
    """A reading list with at least one timestamp shared by two readings."""
    readings = draw(reading_lists())
    if not readings:
        readings = [
            make_reading(0, draw(st.uuids()), BASE, Decimal(0), ReadingStatus.VALID)
        ]
    original = draw(st.sampled_from(readings))
    twin = make_reading(
        len(readings) + 100,
        original.meter_id,
        original.recorded_at,
        draw(kwh_values()),
        draw(st.sampled_from(ReadingStatus)),
    )
    position = draw(st.integers(0, len(readings)))
    return readings[:position] + [twin] + readings[position:]


# --------------------------------------------------------------------------
# Test local helpers (exact, float free, independent of energyiq internals)
# --------------------------------------------------------------------------


def microseconds(delta: timedelta) -> int:
    return delta // ONE_US


def round_half_even(value: Fraction, places: int) -> Decimal:
    """Round a nonnegative rational once, half even, to ``places`` decimals."""
    scaled = value * 10**places
    quotient, remainder = divmod(scaled.numerator, scaled.denominator)
    twice = 2 * remainder
    if twice > scaled.denominator or (twice == scaled.denominator and quotient % 2):
        quotient += 1
    return Decimal(f"{quotient}e-{places}")


def exact_sum(values: Iterable[Decimal]) -> Decimal:
    total = Decimal(0)
    with localcontext(exact_kwh_context()):
        for value in values:
            total += value
    return total


def key_of(interval: ConsumptionInterval) -> IntervalKey:
    return interval.previous_reading_id, interval.current_reading_id


def kwh_of(interval: ConsumptionInterval) -> Decimal:
    assert interval.consumption_kwh is not None
    return interval.consumption_kwh


def measured_keys(summary: ConsumptionWindowSummary) -> list[IntervalKey]:
    return [key_of(item.interval) for item in summary.measured_intervals]


def assert_no_float(value: object, path: str = "summary") -> None:
    assert not isinstance(value, float), f"{path} is a float"
    if is_dataclass(value) and not isinstance(value, type):
        for field in fields(value):
            assert_no_float(getattr(value, field.name), f"{path}.{field.name}")
    elif isinstance(value, tuple):
        for index, item in enumerate(cast(tuple[object, ...], value)):
            assert_no_float(item, f"{path}[{index}]")


def expected_reason(
    previous: Reading, current: Reading, pair_events: Sequence[MeterEvent]
) -> IntervalReason | None:
    """The spec 0004 precedence for one consecutive pair, restated."""
    if pair_events:
        if any(event.approved_by is None for event in pair_events):
            return IntervalReason.UNAPPROVED_EVENT
        if any(event.event_type in UNSUPPORTED_TYPES for event in pair_events):
            return IntervalReason.UNSUPPORTED_EVENT
        return IntervalReason.METER_BOUNDARY
    if ReadingStatus.FLAGGED in (previous.status, current.status):
        return IntervalReason.FLAGGED_READING
    if current.cumulative_kwh < previous.cumulative_kwh:
        return IntervalReason.UNEXPLAINED_DECREASE
    return None


# --------------------------------------------------------------------------
# AC-2: ordering stability
# --------------------------------------------------------------------------


@given(reading_lists())
def test_order_is_a_stable_time_ordered_permutation(readings: list[Reading]) -> None:
    result = order_readings(readings)

    assert Counter(map(id, result.ordered)) == Counter(map(id, readings))
    assert all(
        earlier.recorded_at <= later.recorded_at
        for earlier, later in pairwise(result.ordered)
    )
    expected = tuple(
        reading
        for instant in sorted({reading.recorded_at for reading in readings})
        for reading in readings
        if reading.recorded_at == instant
    )
    assert len(result.ordered) == len(expected)
    assert all(
        actual is wanted
        for actual, wanted in zip(result.ordered, expected, strict=True)
    )


@given(reading_lists())
def test_conflicts_group_every_repeated_timestamp(readings: list[Reading]) -> None:
    result = order_readings(readings)

    counts = Counter(reading.recorded_at for reading in readings)
    repeated = sorted(instant for instant, count in counts.items() if count > 1)
    assert [conflict.recorded_at for conflict in result.conflicts] == repeated
    for conflict in result.conflicts:
        expected_indices = [
            index
            for index, reading in enumerate(readings)
            if reading.recorded_at == conflict.recorded_at
        ]
        assert [entry.input_index for entry in conflict.entries] == expected_indices
        for entry in conflict.entries:
            assert entry.reading is readings[entry.input_index]


@given(reading_lists())
def test_ordering_an_ordered_result_changes_nothing(readings: list[Reading]) -> None:
    once = order_readings(readings)
    twice = order_readings(once.ordered)

    assert twice.ordered == once.ordered
    assert all(a is b for a, b in zip(twice.ordered, once.ordered, strict=True))
    assert [c.recorded_at for c in twice.conflicts] == [
        c.recorded_at for c in once.conflicts
    ]


@given(shuffled_chains())
def test_distinct_timestamps_order_ignores_input_order(
    case: tuple[ReadingOrderResult, list[Reading]],
) -> None:
    order, shuffled = case

    assert order_readings(shuffled) == order


@given(reading_lists())
def test_single_pass_iterator_matches_list(readings: list[Reading]) -> None:
    assert order_readings(iter(readings)) == order_readings(readings)


# --------------------------------------------------------------------------
# AC-3: interval boundary rules
# --------------------------------------------------------------------------


@given(scenarios())
def test_intervals_follow_the_pair_rules(scenario: Scenario) -> None:
    intervals = scenario.intervals
    candidates = [
        reading
        for reading in scenario.order.ordered
        if reading.status is not ReadingStatus.VOIDED
    ]
    events_by_time = sorted(scenario.events, key=lambda event: event.effective_at)

    assert len(intervals) == max(0, len(candidates) - 1)
    for earlier, later in pairwise(intervals):
        assert earlier.end == later.start
    for interval, (previous, current) in zip(
        intervals, pairwise(candidates), strict=True
    ):
        assert interval.meter_id == scenario.meter_id
        assert interval.start == previous.recorded_at
        assert interval.end == current.recorded_at
        assert interval.previous_reading_id == previous.id
        assert interval.current_reading_id == current.id

        pair_events = [
            event
            for event in events_by_time
            if previous.recorded_at < event.effective_at <= current.recorded_at
        ]
        assert interval.event_ids == tuple(event.id for event in pair_events)

        reason = expected_reason(previous, current, pair_events)
        assert interval.reason == reason
        if reason is None:
            assert interval.status is IntervalStatus.VALID
            with localcontext(exact_kwh_context()):
                expected_kwh = current.cumulative_kwh - previous.cumulative_kwh
            assert interval.consumption_kwh == expected_kwh
        else:
            assert interval.status is IntervalStatus.INVALID
            assert interval.consumption_kwh is None


@given(colliding_lists())
def test_timestamp_collision_rejects_the_whole_chain(readings: list[Reading]) -> None:
    result = order_readings(readings)
    assert result.conflicts

    with pytest.raises(ValueError):
        compute_intervals(result, ())
    forged = ReadingOrderResult(ordered=result.ordered, conflicts=())
    with pytest.raises(ValueError):
        compute_intervals(forged, ())


# --------------------------------------------------------------------------
# AC-4: exact window tiling
# --------------------------------------------------------------------------


@given(window_cases())
def test_window_summary_tiles_the_window_exactly(
    case: tuple[Scenario, tuple[datetime, datetime]],
) -> None:
    scenario, (window_start, window_end) = case
    intervals = scenario.intervals
    by_key = {key_of(interval): interval for interval in intervals}

    summary = summarize_consumption(
        intervals, scenario.meter_id, window_start, window_end
    )

    # Measured intervals plus gaps cover the window with no hole or overlap.
    segments = sorted(
        [
            (item.interval.start, item.interval.end)
            for item in summary.measured_intervals
        ]
        + [(gap.start, gap.end) for gap in summary.gaps]
    )
    assert segments
    assert segments[0][0] == window_start
    assert segments[-1][1] == window_end
    for (_, end), (start, _) in pairwise(segments):
        assert end == start

    measured_durations = [item.duration for item in summary.measured_intervals]
    assert summary.covered == sum(measured_durations, timedelta(0))
    assert summary.uncovered == sum(
        (gap.duration for gap in summary.gaps), timedelta(0)
    )
    assert summary.covered + summary.uncovered == window_end - window_start

    # Exactly the valid intervals fully inside the window are measured.
    expected_measured = [
        interval
        for interval in intervals
        if interval.status is IntervalStatus.VALID
        and window_start <= interval.start
        and interval.end <= window_end
    ]
    assert measured_keys(summary) == [key_of(item) for item in expected_measured]
    for item in summary.measured_intervals:
        assert item.interval.status is IntervalStatus.VALID
        assert window_start <= item.interval.start
        assert item.interval.end <= window_end
    assert summary.measured_kwh == exact_sum(kwh_of(i) for i in expected_measured)

    # Interval gaps come only from the right kind of interval.
    segment_keys = list(measured_keys(summary))
    for gap in summary.gaps:
        if gap.reason in (GapReason.PARTIAL_INTERVAL, GapReason.INVALID_INTERVAL):
            assert gap.previous_reading_id is not None
            assert gap.current_reading_id is not None
            key = (gap.previous_reading_id, gap.current_reading_id)
            segment_keys.append(key)
            source = by_key[key]
            assert gap.start == max(source.start, window_start)
            assert gap.end == min(source.end, window_end)
            if gap.reason is GapReason.PARTIAL_INTERVAL:
                assert source.status is IntervalStatus.VALID
                assert source.start < window_start or source.end > window_end
                assert gap.event_ids == ()
            else:
                assert source.status is IntervalStatus.INVALID
                assert gap.interval_reason == source.reason
                assert gap.event_ids == source.event_ids
        elif gap.reason is GapReason.NO_INTERVALS:
            assert not intervals
        elif gap.reason is GapReason.BEFORE_FIRST_READING:
            assert intervals and gap.end <= intervals[0].start
        else:
            assert gap.reason is GapReason.AFTER_LAST_READING
            assert intervals and gap.start >= intervals[-1].end

    # Each interval that overlaps the window yields exactly one segment.
    segment_counts = Counter(segment_keys)
    for interval in intervals:
        overlaps = interval.end > window_start and interval.start < window_end
        assert segment_counts[key_of(interval)] == (1 if overlaps else 0)

    # Ratio and average: the exact rational, rounded once, half even.
    covered_us = microseconds(summary.covered)
    window_us = microseconds(window_end - window_start)
    assert summary.coverage_ratio == round_half_even(
        Fraction(covered_us, window_us), RATIO_PLACES
    )
    assert summary.coverage_ratio.as_tuple().exponent == -RATIO_PLACES
    if covered_us == 0:
        assert summary.average_kwh_per_day is None
    else:
        expected_average = round_half_even(
            Fraction(summary.measured_kwh) * MICROSECONDS_PER_DAY / covered_us,
            RATE_PLACES,
        )
        assert summary.average_kwh_per_day == expected_average
        assert summary.average_kwh_per_day is not None
        assert summary.average_kwh_per_day.as_tuple().exponent == -RATE_PLACES

    assert_no_float(summary)


# --------------------------------------------------------------------------
# AC-5: additivity over adjacent windows
# --------------------------------------------------------------------------


@given(cut_cases())
def test_adjacent_windows_never_count_an_interval_twice(
    case: tuple[Scenario, tuple[datetime, ...]],
) -> None:
    scenario, cuts = case
    intervals = scenario.intervals
    pieces = [
        summarize_consumption(intervals, scenario.meter_id, start, end)
        for start, end in pairwise(cuts)
    ]
    whole = summarize_consumption(intervals, scenario.meter_id, cuts[0], cuts[-1])

    piece_keys = [key for piece in pieces for key in measured_keys(piece)]
    assert len(piece_keys) == len(set(piece_keys))

    interior = cuts[1:-1]
    crossing = [
        interval
        for interval in intervals
        if interval.status is IntervalStatus.VALID
        and cuts[0] <= interval.start
        and interval.end <= cuts[-1]
        and any(interval.start < cut < interval.end for cut in interior)
    ]
    crossing_keys = {key_of(interval) for interval in crossing}
    assert crossing_keys.isdisjoint(piece_keys)
    whole_keys = measured_keys(whole)
    assert len(whole_keys) == len(set(whole_keys))
    assert set(whole_keys) == set(piece_keys) | crossing_keys

    assert whole.measured_kwh == exact_sum(
        [piece.measured_kwh for piece in pieces] + [kwh_of(i) for i in crossing]
    )
    assert whole.covered == sum(
        [piece.covered for piece in pieces]
        + [interval.end - interval.start for interval in crossing],
        timedelta(0),
    )
