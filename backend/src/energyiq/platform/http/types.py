"""Shared request field types for the HTTP contract (spec 0008 AC-4)."""

from datetime import UTC, datetime
from functools import cache
from typing import Annotated
from zoneinfo import available_timezones

from pydantic import AfterValidator, AwareDatetime, BeforeValidator, StringConstraints
from pydantic_core import PydanticCustomError

KWH_PATTERN = r"^[0-9]{1,12}(\.[0-9]{1,6})?$"


def parse_utc_instant(value: object) -> datetime:
    """Parse an ISO 8601 string with an explicit offset and convert it to UTC.

    FastAPI validates bodies as Python objects, where Pydantic strict mode
    rejects every string and lax mode accepts JSON numbers and numeric
    strings as Unix times. Parsing here keeps one rule: a JSON string with an
    explicit offset, nothing else.
    """
    if not isinstance(value, str):
        raise PydanticCustomError("invalid_type", "Value has the wrong JSON type.")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise PydanticCustomError(
            "invalid_datetime", "Value must be an ISO 8601 string."
        ) from None
    if parsed.utcoffset() is None:
        raise PydanticCustomError(
            "invalid_datetime", "Value must include an explicit offset."
        )
    try:
        return parsed.astimezone(UTC)
    except OverflowError:
        raise PydanticCustomError(
            "datetime_out_of_range", "Value is outside the supported range."
        ) from None


KwhString = Annotated[str, StringConstraints(pattern=KWH_PATTERN)]
"""Decimal kWh text; JSON numbers fail because lax ``str`` never coerces them."""

UtcInstant = Annotated[AwareDatetime, BeforeValidator(parse_utc_instant)]
"""An instant given with an explicit offset, delivered to code as UTC."""


# Spec 0009/0002 text fields ---------------------------------------------------


@cache
def iana_timezones() -> frozenset[str]:
    """Every zone name ``zoneinfo`` can load (from ``tzdata`` on Windows)."""
    return frozenset(available_timezones())


def check_timezone(value: str) -> str:
    if value not in iana_timezones():
        raise PydanticCustomError(
            "invalid_timezone", "Value must be an IANA time zone name."
        )
    return value


def trimmed(minimum: int, maximum: int) -> AfterValidator:
    """Strip surrounding whitespace, then require ``minimum..maximum`` chars."""

    def check(value: str) -> str:
        value = value.strip()
        if not minimum <= len(value) <= maximum:
            raise PydanticCustomError(
                "invalid_text_length", "Text length is out of range."
            )
        return value

    return AfterValidator(check)


def reject_null(value: object) -> object:
    """A PATCH field that may be omitted but never set to ``null``."""
    if value is None:
        raise PydanticCustomError("invalid_type", "Value has the wrong JSON type.")
    return value


IanaTimezone = Annotated[str, AfterValidator(check_timezone)]
"""An IANA zone name, exactly as ``zoneinfo`` spells it."""
