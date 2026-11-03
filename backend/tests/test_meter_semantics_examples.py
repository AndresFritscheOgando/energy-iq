"""Worked examples E1 to E13 from docs/12-METER-SEMANTICS.md.

Each test mirrors exactly one example in the document, with the same numbers.
If a test here changes, the document must change with it (spec 0007, AC-7).
All instants are UTC on November 2026 dates. Values and IDs are synthetic.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from energyiq.readings import (
    ConsumptionInterval,
    GapReason,
    IntervalReason,
    IntervalStatus,
    MeterEvent,
    MeterEventType,
    Reading,
    ReadingSource,
    ReadingStatus,
    compute_intervals,
    normalize_intervals,
    order_readings,
    summarize_consumption,
)

METER = uuid4()
APPROVER = uuid4()
CREATED = datetime(2026, 11, 1, tzinfo=UTC)


def at(day: int, hour: int = 12) -> datetime:
    return datetime(2026, 11, day, hour, tzinfo=UTC)


def r(
    value: str,
    recorded_at: datetime,
    *,
    status: ReadingStatus = ReadingStatus.VALID,
    original_local_date: date | None = None,
) -> Reading:
    return Reading(
        id=uuid4(),
        meter_id=METER,
        recorded_at=recorded_at,
        cumulative_kwh=Decimal(value),
        source=ReadingSource.MANUAL,
        status=status,
        created_at=CREATED,
        original_local_date=original_local_date,
    )


def ev(
    kind: MeterEventType, effective_at: datetime, *, approved: bool = True
) -> MeterEvent:
    return MeterEvent(
        id=uuid4(),
        meter_id=METER,
        event_type=kind,
        effective_at=effective_at,
        created_at=CREATED,
        approved_by=APPROVER if approved else None,
        approved_at=CREATED if approved else None,
    )


def intervals(
    readings: list[Reading], events: list[MeterEvent] | None = None
) -> tuple[ConsumptionInterval, ...]:
    return compute_intervals(order_readings(readings), events or [])


def assert_invalid(
    interval: ConsumptionInterval,
    reason: IntervalReason,
    event_ids: tuple[UUID, ...] = (),
) -> None:
    assert interval.status is IntervalStatus.INVALID
    assert interval.reason is reason
    assert interval.consumption_kwh is None
    assert interval.event_ids == event_ids


def test_e1_normal_pair() -> None:
    (interval,) = intervals([r("13007.10", at(1)), r("13019.30", at(2))])
    (normalized,) = normalize_intervals([interval])

    assert interval.status is IntervalStatus.VALID
    assert interval.consumption_kwh == Decimal("12.20")
    assert str(normalized.kwh_per_day) == "12.200000"


def test_e2_no_use() -> None:
    (interval,) = intervals([r("13019.30", at(2)), r("13019.30", at(3))])

    assert interval.status is IntervalStatus.VALID
    assert interval.reason is None
    assert interval.consumption_kwh == Decimal(0)


def test_e3_non_24_hour_interval() -> None:
    (interval,) = intervals([r("100.0", at(1, 0)), r("106.0", at(2, 12))])
    (normalized,) = normalize_intervals([interval])

    assert interval.consumption_kwh == Decimal("6.0")
    assert normalized.duration.total_seconds() == 36 * 3600
    assert str(normalized.kwh_per_day) == "4.000000"


def test_e4_unexplained_decrease() -> None:
    (interval,) = intervals([r("13019.30", at(2)), r("13010.00", at(3))])

    assert_invalid(interval, IntervalReason.UNEXPLAINED_DECREASE)


def test_e5_approved_reset_at_reading_instant() -> None:
    reset = ev(MeterEventType.RESET, at(3))
    first, second = intervals(
        [r("13019.30", at(2)), r("0.40", at(3)), r("5.40", at(4))], [reset]
    )

    assert_invalid(first, IntervalReason.METER_BOUNDARY, (reset.id,))
    assert second.status is IntervalStatus.VALID
    assert second.consumption_kwh == Decimal("5.00")


def test_e6_unapproved_reset() -> None:
    reset = ev(MeterEventType.RESET, at(3), approved=False)
    first, second = intervals(
        [r("13019.30", at(2)), r("0.40", at(3)), r("5.40", at(4))], [reset]
    )

    assert_invalid(first, IntervalReason.UNAPPROVED_EVENT, (reset.id,))
    assert second.status is IntervalStatus.VALID
    assert second.consumption_kwh == Decimal("5.00")


def test_e7_approved_rollover() -> None:
    rollover = ev(MeterEventType.ROLLOVER, at(2))
    (interval,) = intervals([r("99990", at(1)), r("12", at(2))], [rollover])

    assert_invalid(interval, IntervalReason.UNSUPPORTED_EVENT, (rollover.id,))


def test_e8_approved_calibration() -> None:
    calibration = ev(MeterEventType.CALIBRATION, at(1, 18))
    (interval,) = intervals([r("500.0", at(1)), r("510.0", at(2))], [calibration])

    assert_invalid(interval, IntervalReason.UNSUPPORTED_EVENT, (calibration.id,))


def test_e9_flagged_middle_reading() -> None:
    result = intervals(
        [
            r("100.0", at(1)),
            r("150.0", at(2), status=ReadingStatus.FLAGGED),
            r("120.0", at(3)),
        ]
    )

    assert len(result) == 2
    for interval in result:
        assert_invalid(interval, IntervalReason.FLAGGED_READING)


def test_e10_voided_middle_reading() -> None:
    start, end = r("100.0", at(1)), r("120.0", at(3))
    (interval,) = intervals(
        [start, r("150.0", at(2), status=ReadingStatus.VOIDED), end]
    )

    assert interval.status is IntervalStatus.VALID
    assert (interval.previous_reading_id, interval.current_reading_id) == (
        start.id,
        end.id,
    )
    assert (interval.start, interval.end) == (at(1), at(3))
    assert interval.consumption_kwh == Decimal("20.0")


def test_e11_window_cuts_an_interval() -> None:
    chain = intervals(
        [r("100.0", at(1, 0)), r("110.0", at(2, 0)), r("130.0", at(3, 0))]
    )
    summary = summarize_consumption(chain, METER, at(1, 0), at(2, 12))

    assert summary.measured_kwh == Decimal("10.0")
    (gap,) = summary.gaps
    assert gap.reason is GapReason.PARTIAL_INTERVAL
    assert (gap.start, gap.end) == (at(2, 0), at(2, 12))
    assert str(summary.coverage_ratio) == "0.6667"


def test_e12_implausible_spike() -> None:
    (interval,) = intervals([r("13049.0", at(1)), r("130490.0", at(2))])

    assert interval.status is IntervalStatus.VALID
    assert interval.consumption_kwh == Decimal("117441.0")


def test_e13_two_date_only_readings_same_local_date() -> None:
    # 12:00 in America/Santo_Domingo (UTC-4, no daylight saving) is 16:00 UTC.
    local_date = date(2026, 11, 3)
    first = r("200.0", at(3, 16), original_local_date=local_date)
    second = r("201.0", at(3, 16), original_local_date=local_date)
    result = order_readings([first, second])

    (conflict,) = result.conflicts
    assert conflict.recorded_at == at(3, 16)
    assert [entry.reading for entry in conflict.entries] == [first, second]
    with pytest.raises(ValueError, match="conflicts"):
        compute_intervals(result, [])
