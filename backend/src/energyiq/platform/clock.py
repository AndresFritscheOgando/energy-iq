"""Injectable source of the current UTC instant."""

from datetime import UTC, datetime


def get_now() -> datetime:
    """Return the current instant as an aware UTC datetime."""

    return datetime.now(UTC)
