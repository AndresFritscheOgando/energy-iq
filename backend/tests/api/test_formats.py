from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from energyiq.platform.http.formats import format_decimal, format_duration, format_utc


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal("0E-8"), "0.00000000"),
        (Decimal(0), "0"),
        (Decimal("0.0000"), "0.0000"),
        (Decimal("12.500000"), "12.500000"),
        (Decimal("1E+3"), "1000"),
        (Decimal("999999999999.999999"), "999999999999.999999"),
    ],
)
def test_format_decimal_is_fixed_point(value: Decimal, expected: str) -> None:
    assert format_decimal(value) == expected


@pytest.mark.parametrize("value", [Decimal("NaN"), Decimal("Infinity")])
def test_format_decimal_rejects_non_finite(value: Decimal) -> None:
    with pytest.raises(ValueError, match="finite"):
        format_decimal(value)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (datetime(2026, 10, 25, 16, tzinfo=UTC), "2026-10-25T16:00:00Z"),
        (
            datetime(2026, 10, 25, 16, 0, 0, 1, tzinfo=UTC),
            "2026-10-25T16:00:00.000001Z",
        ),
        (
            datetime(2026, 10, 25, 16, 0, 0, 500000, tzinfo=UTC),
            "2026-10-25T16:00:00.500000Z",
        ),
        (datetime(1, 1, 1, tzinfo=UTC), "0001-01-01T00:00:00Z"),
        (datetime(2026, 1, 1, tzinfo=timezone(timedelta(0))), "2026-01-01T00:00:00Z"),
    ],
)
def test_format_utc_exact_text(value: datetime, expected: str) -> None:
    assert format_utc(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        datetime(2026, 1, 1),
        datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=-4))),
    ],
)
def test_format_utc_rejects_naive_and_offset(value: datetime) -> None:
    with pytest.raises(ValueError, match="UTC"):
        format_utc(value)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (timedelta(0), "PT0S"),
        (timedelta(days=1, hours=2, minutes=30), "P1DT2H30M"),
        (timedelta(microseconds=1), "PT0.000001S"),
        (timedelta(days=3), "P3D"),
        (timedelta(hours=12), "PT12H"),
        (timedelta(seconds=90), "PT1M30S"),
        (timedelta(seconds=5, microseconds=500000), "PT5.5S"),
        (timedelta(days=1, microseconds=1), "P1DT0.000001S"),
        (
            timedelta(hours=7, minutes=59, seconds=59, microseconds=999999),
            "PT7H59M59.999999S",
        ),
        (timedelta(days=400), "P400D"),
    ],
)
def test_format_duration_exact_text(value: timedelta, expected: str) -> None:
    assert format_duration(value) == expected


def test_format_duration_rejects_negative() -> None:
    with pytest.raises(ValueError, match="negative"):
        format_duration(timedelta(microseconds=-1))
