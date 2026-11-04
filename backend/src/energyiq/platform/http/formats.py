"""Exact text formats for API output (spec 0008 AC-3).

The API renders values itself instead of relying on library defaults, which
can change between versions: Decimals as fixed point strings, instants as
``Z`` suffixed UTC text, and durations as ISO 8601.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

_MICROSECONDS_PER_SECOND = 1_000_000
_MICROSECONDS_PER_DAY = 86_400 * _MICROSECONDS_PER_SECOND


def format_decimal(value: Decimal) -> str:
    """Fixed point text of the exact value, never exponent form."""
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError("value must be a finite Decimal")
    return format(value, "f")


def format_utc(value: datetime) -> str:
    """``YYYY-MM-DDTHH:MM:SSZ``, with six fraction digits when nonzero."""
    if value.utcoffset() != timedelta(0):
        raise ValueError("value must be an aware UTC datetime")
    text = (
        f"{value.year:04d}-{value.month:02d}-{value.day:02d}"
        f"T{value.hour:02d}:{value.minute:02d}:{value.second:02d}"
    )
    if value.microsecond:
        text += f".{value.microsecond:06d}"
    return text + "Z"


def format_duration(value: timedelta) -> str:
    """ISO 8601 ``P[nD]T[nH][nM][n[.f]S]``; zero parts omitted, zero is ``PT0S``."""
    if value < timedelta(0):
        raise ValueError("duration cannot be negative")
    total = (
        value.days * 86_400 + value.seconds
    ) * _MICROSECONDS_PER_SECOND + value.microseconds
    days, rest = divmod(total, _MICROSECONDS_PER_DAY)
    seconds_total, micros = divmod(rest, _MICROSECONDS_PER_SECOND)
    hours, rest_seconds = divmod(seconds_total, 3_600)
    minutes, seconds = divmod(rest_seconds, 60)

    date_part = f"{days}D" if days else ""
    time_part = ""
    if hours:
        time_part += f"{hours}H"
    if minutes:
        time_part += f"{minutes}M"
    if seconds or micros:
        fraction = f".{micros:06d}".rstrip("0") if micros else ""
        time_part += f"{seconds}{fraction}S"

    if not date_part and not time_part:
        return "PT0S"
    return "P" + date_part + (f"T{time_part}" if time_part else "")


def format_instant(value: datetime) -> str:
    """``format_utc`` of any aware instant, such as a ``timestamptz`` value."""
    return format_utc(value.astimezone(UTC))
