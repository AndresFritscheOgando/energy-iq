from dataclasses import FrozenInstanceError
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import ROUND_UP, Decimal, getcontext, localcontext
from uuid import UUID

import pytest

from energyiq.readings import (
    MeterEvent,
    MeterEventType,
    Reading,
    ReadingSource,
    ReadingStatus,
)

READING_ID = UUID("00000000-0000-0000-0000-000000000001")
METER_ID = UUID("00000000-0000-0000-0000-000000000002")
ACTOR_ID = UUID("00000000-0000-0000-0000-000000000003")
INSTANT = datetime(2026, 11, 3, 12, tzinfo=UTC)


def make_reading(**changes: object) -> Reading:
    values: dict[str, object] = {
        "id": READING_ID,
        "meter_id": METER_ID,
        "recorded_at": INSTANT,
        "cumulative_kwh": Decimal("13007.100000"),
        "source": ReadingSource.MANUAL,
        "status": ReadingStatus.VALID,
        "created_at": INSTANT,
    }
    values.update(changes)
    return Reading(**values)  # type: ignore[arg-type]


def make_event(**changes: object) -> MeterEvent:
    values: dict[str, object] = {
        "id": READING_ID,
        "meter_id": METER_ID,
        "event_type": MeterEventType.REPLACED,
        "effective_at": INSTANT,
        "created_at": INSTANT,
    }
    values.update(changes)
    return MeterEvent(**values)  # type: ignore[arg-type]


def test_reading_keeps_exact_value_identity_and_provenance():
    reading = make_reading(
        original_local_date=date(2026, 11, 3),
        note="Manual check",
        source_ref="entry-1",
    )

    assert reading.id == READING_ID
    assert reading.meter_id == METER_ID
    assert str(reading.cumulative_kwh) == "13007.100000"
    assert reading.recorded_at == INSTANT
    assert reading.original_local_date == date(2026, 11, 3)
    with pytest.raises(FrozenInstanceError):
        reading.status = ReadingStatus.VOIDED  # pyright: ignore[reportAttributeAccessIssue]


@pytest.mark.parametrize(
    "value",
    [Decimal(0), Decimal("-0"), Decimal("999999999999.999999"), Decimal("1.0000000")],
)
def test_reading_accepts_exact_scale_and_boundaries(value: Decimal):
    assert make_reading(cumulative_kwh=value).cumulative_kwh is value


@pytest.mark.parametrize(
    ("value", "reason"),
    [
        (Decimal("-0.000001"), "negative"),
        (Decimal("999999999999.9999991"), "maximum"),
        (Decimal("1.0000001"), "six fractional"),
        (Decimal("1E-1000000"), "six fractional"),
        (Decimal("NaN"), "finite"),
        (Decimal("sNaN"), "finite"),
        (Decimal("Infinity"), "finite"),
    ],
)
def test_reading_rejects_invalid_kwh_without_context_mutation(
    value: Decimal, reason: str
):
    with localcontext() as context:
        context.prec = 3
        context.rounding = ROUND_UP
        context.clear_flags()
        before = repr(context)
        with pytest.raises(ValueError, match=reason):
            make_reading(cumulative_kwh=value)
        assert getcontext() is context
        assert repr(context) == before


@pytest.mark.parametrize("value", [1, 1.2, True, "1", None])
def test_reading_rejects_non_decimal_kwh(value: object):
    with pytest.raises(TypeError, match="cumulative_kwh.*Decimal"):
        make_reading(cumulative_kwh=value)


@pytest.mark.parametrize("field", ["id", "meter_id"])
def test_models_require_uuid_identity(field: str):
    with pytest.raises(TypeError, match=f"{field}.*UUID"):
        make_reading(**{field: str(METER_ID)})
    with pytest.raises(TypeError, match=f"{field}.*UUID"):
        make_event(**{field: str(METER_ID)})


@pytest.mark.parametrize("field", ["recorded_at", "created_at"])
@pytest.mark.parametrize(
    "invalid",
    [
        date(2026, 11, 3),
        datetime(2026, 11, 3),
        datetime(2026, 11, 3, tzinfo=timezone(timedelta(hours=-4))),
    ],
)
def test_reading_requires_utc_instants(field: str, invalid: object):
    with pytest.raises((TypeError, ValueError), match=field):
        make_reading(**{field: invalid})


@pytest.mark.parametrize("field", ["effective_at", "created_at", "approved_at"])
@pytest.mark.parametrize(
    "invalid",
    [
        date(2026, 11, 3),
        datetime(2026, 11, 3),
        datetime(2026, 11, 3, tzinfo=timezone(timedelta(hours=-4))),
    ],
)
def test_event_requires_utc_instants(field: str, invalid: object):
    changes = {field: invalid}
    if field == "approved_at":
        changes["approved_by"] = ACTOR_ID
    with pytest.raises((TypeError, ValueError), match=field):
        make_event(**changes)


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("source", "manual"),
        ("status", "valid"),
        ("original_local_date", INSTANT),
        ("note", " "),
        ("source_ref", 3),
    ],
)
def test_reading_rejects_invalid_metadata(field: str, invalid: object):
    with pytest.raises((TypeError, ValueError), match=field):
        make_reading(**{field: invalid})


def test_event_preserves_kind_and_approval_metadata():
    event = make_event(approved_by=ACTOR_ID, approved_at=INSTANT, note="New meter")

    assert event.event_type is MeterEventType.REPLACED
    assert event.meter_id == METER_ID
    assert event.approved_by == ACTOR_ID
    assert event.approved_at == INSTANT
    with pytest.raises(FrozenInstanceError):
        event.event_type = MeterEventType.RESET  # pyright: ignore[reportAttributeAccessIssue]


@pytest.mark.parametrize("kind", list(MeterEventType))
def test_all_documented_event_kinds_are_available(kind: MeterEventType):
    assert make_event(event_type=kind).event_type is kind


@pytest.mark.parametrize(
    "changes",
    [
        {"event_type": "reset"},
        {"approved_by": ACTOR_ID},
        {"approved_at": INSTANT},
        {"approved_by": "actor", "approved_at": INSTANT},
        {"note": "  "},
    ],
)
def test_event_rejects_invalid_kind_or_metadata(changes: dict[str, object]):
    with pytest.raises((TypeError, ValueError)):
        make_event(**changes)


def test_models_do_not_resolve_cross_record_conflicts():
    first = make_reading()
    duplicate = make_reading(id=ACTOR_ID, cumulative_kwh=Decimal(1))
    event = make_event(event_type=MeterEventType.RESET)

    assert first.recorded_at == duplicate.recorded_at == event.effective_at
    assert first.cumulative_kwh > duplicate.cumulative_kwh
