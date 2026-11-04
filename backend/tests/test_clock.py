from datetime import UTC, datetime, timedelta

from energyiq.platform.clock import get_now


def test_get_now_is_aware_utc() -> None:
    now = get_now()

    assert now.tzinfo is not None
    assert now.utcoffset() == timedelta(0)


def test_get_now_is_current() -> None:
    before = datetime.now(UTC)
    now = get_now()
    after = datetime.now(UTC)

    assert before <= now <= after
