"""Bill window mapping and the billed versus measured comparison (spec 0012/0006 AC-4)."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from energyiq.readings import (
    ConsumptionWindowSummary,
    Reading,
    ReadingSource,
    ReadingStatus,
    compute_intervals,
    order_readings,
    summarize_consumption,
)
from energyiq.reconciliation.service import (
    NotComparable,
    bill_window,
    compare,
    period_days,
    too_long,
)

METER = uuid4()
TZ = "America/Santo_Domingo"  # UTC-4 all year


def _reading(at: datetime, kwh: str) -> Reading:
    return Reading(
        id=uuid4(),
        meter_id=METER,
        recorded_at=at,
        cumulative_kwh=Decimal(kwh),
        source=ReadingSource.MANUAL,
        status=ReadingStatus.VALID,
        created_at=at,
    )


def _summary(
    start: datetime, end: datetime, readings: list[Reading]
) -> ConsumptionWindowSummary:
    intervals = compute_intervals(order_readings(readings), [])
    return summarize_consumption(intervals, METER, start, end)


def test_inclusive_local_dates_map_to_a_half_open_utc_window() -> None:
    start, end = bill_window(date(2026, 10, 1), date(2026, 10, 31), TZ)
    assert start == datetime(2026, 10, 1, 4, tzinfo=UTC)
    assert end == datetime(2026, 11, 1, 4, tzinfo=UTC)


def test_a_one_day_period_is_a_valid_window() -> None:
    start, end = bill_window(date(2026, 10, 5), date(2026, 10, 5), TZ)
    assert end - start == timedelta(days=1)
    assert period_days(date(2026, 10, 5), date(2026, 10, 5)) == 1


def test_window_follows_the_property_time_zone() -> None:
    start, _ = bill_window(date(2026, 10, 1), date(2026, 10, 1), "UTC")
    assert start == datetime(2026, 10, 1, tzinfo=UTC)


def test_full_coverage_gives_a_difference_and_conclusion() -> None:
    start, end = bill_window(date(2026, 10, 1), date(2026, 10, 31), TZ)
    summary = _summary(start, end, [_reading(start, "1000"), _reading(end, "1250")])
    exact = compare(Decimal(250), summary)
    assert (exact.measured_kwh, exact.difference_kwh, exact.conclusion) == (
        Decimal(250),
        Decimal(0),
        "match",
    )
    high = compare(Decimal("260.5"), summary)
    assert (high.difference_kwh, high.conclusion) == (Decimal("10.5"), "mismatch")
    low = compare(Decimal(240), summary)
    assert (low.difference_kwh, low.conclusion) == (Decimal(-10), "mismatch")


def test_true_zero_with_full_coverage_is_a_numeric_zero() -> None:
    start, end = bill_window(date(2026, 10, 1), date(2026, 10, 31), TZ)
    summary = _summary(start, end, [_reading(start, "500"), _reading(end, "500")])
    result = compare(Decimal(0), summary)
    assert result.measured_kwh == Decimal(0)
    assert result.conclusion == "match"


def test_partial_interval_gives_no_difference_and_is_not_prorated() -> None:
    start, end = bill_window(date(2026, 10, 1), date(2026, 10, 31), TZ)
    inside = start + timedelta(days=2)
    summary = _summary(start, end, [_reading(inside, "1000"), _reading(end, "1250")])
    result = compare(Decimal(250), summary)
    assert result.difference_kwh is None and result.conclusion is None
    assert result.reasons == (NotComparable.COVERAGE_INCOMPLETE,)


def test_readings_that_overshoot_the_window_are_a_partial_interval() -> None:
    start, end = bill_window(date(2026, 10, 1), date(2026, 10, 31), TZ)
    summary = _summary(
        start,
        end,
        [
            _reading(start - timedelta(days=1), "900"),
            _reading(end + timedelta(days=1), "1300"),
        ],
    )
    result = compare(Decimal(400), summary)
    assert result.difference_kwh is None and result.conclusion is None
    assert result.measured_kwh is None  # nothing fully inside the window


def test_no_readings_is_not_zero() -> None:
    start, end = bill_window(date(2026, 10, 1), date(2026, 10, 31), TZ)
    result = compare(Decimal(0), _summary(start, end, []))
    assert result.measured_kwh is None
    assert result.difference_kwh is None and result.conclusion is None


def test_period_too_long_is_not_comparable() -> None:
    result = too_long(Decimal(10))
    assert result.reasons == (NotComparable.PERIOD_TOO_LONG,)
    assert result.difference_kwh is None


def test_bill_window_overflow_is_an_error_the_route_can_catch() -> None:
    # Local midnight at +09:00 on 0001-01-01 is before the UTC calendar start.
    with pytest.raises((OverflowError, ValueError)):
        bill_window(date(1, 1, 1), date(1, 1, 2), "Asia/Tokyo")


def test_partial_coverage_withholds_measured_kwh() -> None:
    start, end = bill_window(date(2026, 10, 1), date(2026, 10, 31), TZ)
    summary = _summary(
        start,
        end,
        [_reading(start + timedelta(days=2), "1000"), _reading(end, "1250")],
    )
    result = compare(Decimal(250), summary)
    assert result.measured_kwh is None and result.conclusion is None
