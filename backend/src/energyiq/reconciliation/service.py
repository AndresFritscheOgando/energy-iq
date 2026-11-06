"""Pure comparison of billed kWh with measured kWh (spec 0012/0006 AC-4).

A numeric difference and a mismatch conclusion exist only when the readings
cover the whole bill window with valid intervals. Partial coverage or any gap
returns no difference: unmeasured time is never zero and is never estimated.
Equality is exact; this spec sets no tolerance.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from enum import StrEnum
from zoneinfo import ZoneInfo

from energyiq.readings import ConsumptionWindowSummary

MAX_WINDOW_DAYS = 366


class NotComparable(StrEnum):
    COVERAGE_INCOMPLETE = "coverage_incomplete"
    PERIOD_TOO_LONG = "period_too_long"


@dataclass(frozen=True)
class Comparison:
    billed_kwh: Decimal
    measured_kwh: Decimal | None
    difference_kwh: Decimal | None
    conclusion: str | None  # "match" or "mismatch"; None when not comparable
    reasons: tuple[NotComparable, ...]


def bill_window(start: date, end: date, timezone: str) -> tuple[datetime, datetime]:
    """Inclusive local bill dates as a half open UTC window.

    Starts at local midnight of the first date and ends at local midnight after
    the last date, in the property's time zone.
    """
    zone = ZoneInfo(timezone)
    first = datetime.combine(start, time.min, tzinfo=zone).astimezone(UTC)
    after = datetime.combine(end + timedelta(days=1), time.min, tzinfo=zone).astimezone(
        UTC
    )
    return first, after


def period_days(start: date, end: date) -> int:
    return (end - start).days + 1


def too_long(billed_kwh: Decimal) -> Comparison:
    return Comparison(billed_kwh, None, None, None, (NotComparable.PERIOD_TOO_LONG,))


def compare(billed_kwh: Decimal, summary: ConsumptionWindowSummary) -> Comparison:
    """Compare billed use with the measured summary of the same window."""
    complete = not summary.gaps and summary.uncovered == timedelta(0)
    if not complete:
        # Partial measured kWh is withheld so nobody subtracts it from billed kWh.
        return Comparison(
            billed_kwh, None, None, None, (NotComparable.COVERAGE_INCOMPLETE,)
        )
    difference = billed_kwh - summary.measured_kwh
    return Comparison(
        billed_kwh,
        summary.measured_kwh,
        difference,
        "match" if difference == 0 else "mismatch",
        (),
    )
