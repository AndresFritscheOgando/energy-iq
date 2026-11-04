"""Database enforced rules: one violating row per rule (spec 0009/0001 AC-4).

Every insert runs as the app role inside the rolled back test transaction.
Synthetic data only.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Connection, Table, insert, select
from sqlalchemy.exc import IntegrityError

from energyiq.identity.models import UserRow
from energyiq.platform.audit import AuditEventRow
from energyiq.platform.db import constraint_name
from energyiq.properties.models import MeterRow, PropertyRow
from energyiq.readings.persistence.rows import MeterEventRow, ReadingRow

pytestmark = pytest.mark.db

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
LATER = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)

USERS: Table = UserRow.__table__  # pyright: ignore[reportAssignmentType]
PROPERTIES: Table = PropertyRow.__table__  # pyright: ignore[reportAssignmentType]
METERS: Table = MeterRow.__table__  # pyright: ignore[reportAssignmentType]
EVENTS: Table = MeterEventRow.__table__  # pyright: ignore[reportAssignmentType]
READINGS: Table = ReadingRow.__table__  # pyright: ignore[reportAssignmentType]
AUDIT: Table = AuditEventRow.__table__  # pyright: ignore[reportAssignmentType]


@dataclass(frozen=True)
class Seed:
    user_id: UUID
    property_id: UUID
    meter_id: UUID


def user(**overrides: Any) -> dict[str, Any]:
    return {
        "id": uuid4(),
        "email": f"{uuid4().hex}@example.test",
        "password_hash": "synthetic-hash",
        "created_at": NOW,
    } | overrides


def prop(seed: Seed, **overrides: Any) -> dict[str, Any]:
    return {
        "id": uuid4(),
        "owner_user_id": seed.user_id,
        "nickname": f"Casa {uuid4().hex[:8]}",
        "created_at": NOW,
        "updated_at": NOW,
    } | overrides


def meter(seed: Seed, **overrides: Any) -> dict[str, Any]:
    return {
        "id": uuid4(),
        "property_id": seed.property_id,
        "distributor": "EDESUR",
        "label": f"Meter {uuid4().hex[:8]}",
        "created_at": NOW,
        "updated_at": NOW,
    } | overrides


def event(seed: Seed, **overrides: Any) -> dict[str, Any]:
    return {
        "id": uuid4(),
        "meter_id": seed.meter_id,
        "event_type": "reset",
        "effective_at": NOW,
        "status": "pending",
        "created_by": seed.user_id,
        "created_at": NOW,
    } | overrides


def reading(seed: Seed, **overrides: Any) -> dict[str, Any]:
    return {
        "id": uuid4(),
        "meter_id": seed.meter_id,
        "recorded_at": NOW,
        "cumulative_kwh": Decimal("1234.500000"),
        "source": "manual",
        "status": "valid",
        "created_by": seed.user_id,
        "created_at": NOW,
    } | overrides


def audit(seed: Seed, **overrides: Any) -> dict[str, Any]:
    return {
        "actor_user_id": seed.user_id,
        "action": "property.create",
        "entity_type": "property",
        "entity_id": seed.property_id,
        "occurred_at": NOW,
        "request_id": "req-1",
    } | overrides


@pytest.fixture
def seed(db_connection: Connection) -> Seed:
    ids = Seed(user_id=uuid4(), property_id=uuid4(), meter_id=uuid4())
    db_connection.execute(insert(USERS).values(user(id=ids.user_id)))
    db_connection.execute(insert(PROPERTIES).values(prop(ids, id=ids.property_id)))
    db_connection.execute(insert(METERS).values(meter(ids, id=ids.meter_id)))
    return ids


Rows = list[tuple[Table, dict[str, Any]]]
Case = Callable[[Seed], Rows]

VIOLATIONS: dict[str, tuple[Case, str]] = {
    # users
    "email unique": (
        lambda s: [
            (USERS, user(email="same@example.test")),
            (USERS, user(email="same@example.test")),
        ],
        "uq_users_email",
    ),
    "email length": (
        lambda s: [(USERS, user(email="a" * 243 + "@example.test"))],
        "ck_users_email_length",
    ),
    # properties
    "nickname empty": (
        lambda s: [(PROPERTIES, prop(s, nickname=""))],
        "ck_properties_nickname_length",
    ),
    "nickname too long": (
        lambda s: [(PROPERTIES, prop(s, nickname="n" * 81))],
        "ck_properties_nickname_length",
    ),
    "region too long": (
        lambda s: [(PROPERTIES, prop(s, region="r" * 81))],
        "ck_properties_region_length",
    ),
    "timezone empty": (
        lambda s: [(PROPERTIES, prop(s, timezone=""))],
        "ck_properties_timezone_length",
    ),
    "nickname unique per owner, case insensitive": (
        lambda s: [
            (PROPERTIES, prop(s, nickname="Casa Playa")),
            (PROPERTIES, prop(s, nickname="casa PLAYA")),
        ],
        "uq_properties_owner_nickname_active",
    ),
    "property owner exists": (
        lambda s: [(PROPERTIES, prop(s, owner_user_id=uuid4()))],
        "fk_properties_owner_user_id_users",
    ),
    # meters
    "distributor enumeration": (
        lambda s: [(METERS, meter(s, distributor="edesur"))],
        "ck_meters_distributor",
    ),
    "label empty": (
        lambda s: [(METERS, meter(s, label=""))],
        "ck_meters_label_length",
    ),
    "label too long": (
        lambda s: [(METERS, meter(s, label="l" * 61))],
        "ck_meters_label_length",
    ),
    "register digits below 4": (
        lambda s: [(METERS, meter(s, register_digits=3))],
        "ck_meters_register_digits_range",
    ),
    "register digits above 9": (
        lambda s: [(METERS, meter(s, register_digits=10))],
        "ck_meters_register_digits_range",
    ),
    "active with deactivated_at": (
        lambda s: [(METERS, meter(s, active=True, deactivated_at=NOW))],
        "ck_meters_active_deactivated",
    ),
    "inactive without deactivated_at": (
        lambda s: [(METERS, meter(s, active=False))],
        "ck_meters_active_deactivated",
    ),
    "label unique per property among active, case insensitive": (
        lambda s: [
            (METERS, meter(s, label="Main")),
            (METERS, meter(s, label="MAIN")),
        ],
        "uq_meters_property_label_active",
    ),
    "meter property exists": (
        lambda s: [(METERS, meter(s, property_id=uuid4()))],
        "fk_meters_property_id_properties",
    ),
    # meter events
    "event type enumeration": (
        lambda s: [(EVENTS, event(s, event_type="swap"))],
        "ck_meter_events_event_type",
    ),
    "event status enumeration": (
        lambda s: [
            (EVENTS, event(s, status="done", decided_by=s.user_id, decided_at=NOW))
        ],
        "ck_meter_events_status",
    ),
    "event note too long": (
        lambda s: [(EVENTS, event(s, note="x" * 501))],
        "ck_meter_events_note_length",
    ),
    "pending event with a decision": (
        lambda s: [
            (EVENTS, event(s, status="pending", decided_by=s.user_id, decided_at=NOW))
        ],
        "ck_meter_events_decision_pair",
    ),
    "approved event without decided_at": (
        lambda s: [(EVENTS, event(s, status="approved", decided_by=s.user_id))],
        "ck_meter_events_decision_pair",
    ),
    "rejected event without decided_by": (
        lambda s: [(EVENTS, event(s, status="rejected", decided_at=NOW))],
        "ck_meter_events_decision_pair",
    ),
    "event meter exists": (
        lambda s: [(EVENTS, event(s, meter_id=uuid4()))],
        "fk_meter_events_meter_id_meters",
    ),
    "event creator exists": (
        lambda s: [(EVENTS, event(s, created_by=uuid4()))],
        "fk_meter_events_created_by_users",
    ),
    "event decider exists": (
        lambda s: [
            (EVENTS, event(s, status="approved", decided_by=uuid4(), decided_at=NOW))
        ],
        "fk_meter_events_decided_by_users",
    ),
    # readings
    "negative cumulative kWh": (
        lambda s: [(READINGS, reading(s, cumulative_kwh=Decimal("-0.000001")))],
        "ck_readings_cumulative_kwh_nonnegative",
    ),
    "reading source enumeration": (
        lambda s: [(READINGS, reading(s, source="scan"))],
        "ck_readings_source",
    ),
    "reading status enumeration": (
        lambda s: [(READINGS, reading(s, status="deleted"))],
        "ck_readings_status",
    ),
    "one non voided reading per meter instant": (
        lambda s: [
            (READINGS, reading(s, status="valid")),
            (READINGS, reading(s, status="flagged")),
        ],
        "uq_readings_meter_instant_active",
    ),
    "reading meter exists": (
        lambda s: [(READINGS, reading(s, meter_id=uuid4()))],
        "fk_readings_meter_id_meters",
    ),
    "reading creator exists": (
        lambda s: [(READINGS, reading(s, created_by=uuid4()))],
        "fk_readings_created_by_users",
    ),
    # audit events
    "audit actor exists": (
        lambda s: [(AUDIT, audit(s, actor_user_id=uuid4()))],
        "fk_audit_events_actor_user_id_users",
    ),
}


@pytest.mark.parametrize(("case", "expected"), VIOLATIONS.values(), ids=VIOLATIONS)
def test_violation_names_its_constraint(
    db_connection: Connection, seed: Seed, case: Case, expected: str
) -> None:
    *setup, (table, row) = case(seed)
    for setup_table, setup_row in setup:
        db_connection.execute(insert(setup_table).values(setup_row))

    with pytest.raises(IntegrityError) as excinfo:
        db_connection.execute(insert(table).values(row))

    assert constraint_name(excinfo.value) == expected


ALLOWED: dict[str, Case] = {
    "archived property frees its nickname": lambda s: [
        (PROPERTIES, prop(s, nickname="Casa", archived_at=NOW)),
        (PROPERTIES, prop(s, nickname="casa")),
    ],
    "same nickname for another owner": lambda s: [
        (USERS, user(id=UUID(int=7))),
        (PROPERTIES, prop(s, nickname="Casa")),
        (PROPERTIES, prop(s, owner_user_id=UUID(int=7), nickname="Casa")),
    ],
    "inactive meter frees its label": lambda s: [
        (METERS, meter(s, label="Main", active=False, deactivated_at=NOW)),
        (METERS, meter(s, label="main")),
    ],
    "register digits bounds and null": lambda s: [
        (METERS, meter(s, register_digits=4)),
        (METERS, meter(s, register_digits=9)),
        (METERS, meter(s, register_digits=None)),
    ],
    "voided reading frees its instant": lambda s: [
        (READINGS, reading(s, status="voided")),
        (READINGS, reading(s, status="valid")),
    ],
    "same instant on another meter": lambda s: [
        (METERS, meter(s, id=UUID(int=9))),
        (READINGS, reading(s)),
        (READINGS, reading(s, meter_id=UUID(int=9))),
    ],
    "decided events carry both decision fields": lambda s: [
        (EVENTS, event(s, status="approved", decided_by=s.user_id, decided_at=LATER)),
        (EVENTS, event(s, status="rejected", decided_by=s.user_id, decided_at=LATER)),
    ],
    "zero kWh and the largest NUMERIC(18,6) value": lambda s: [
        (READINGS, reading(s, cumulative_kwh=Decimal(0))),
        (
            READINGS,
            reading(
                s, recorded_at=LATER, cumulative_kwh=Decimal("999999999999.999999")
            ),
        ),
    ],
    "audit event without an actor": lambda s: [
        (AUDIT, audit(s, actor_user_id=None, entity_id=None)),
    ],
}


@pytest.mark.parametrize("case", ALLOWED.values(), ids=ALLOWED)
def test_rows_within_the_rules_are_accepted(
    db_connection: Connection, seed: Seed, case: Case
) -> None:
    for table, row in case(seed):
        db_connection.execute(insert(table).values(row))


def test_server_defaults(db_connection: Connection, seed: Seed) -> None:
    timezone, active = db_connection.execute(
        select(PROPERTIES.c.timezone, METERS.c.active)
        .join(METERS, METERS.c.property_id == PROPERTIES.c.id)
        .where(METERS.c.id == seed.meter_id)
    ).one()
    db_connection.execute(insert(AUDIT).values(audit(seed)))
    metadata, audit_id = db_connection.execute(
        select(AUDIT.c.metadata, AUDIT.c.id)
    ).one()

    assert timezone == "America/Santo_Domingo"
    assert active is True
    assert metadata == {}
    assert isinstance(audit_id, int)


def test_numeric_and_timestamps_round_trip_without_float(
    db_connection: Connection, seed: Seed
) -> None:
    db_connection.execute(
        insert(READINGS).values(reading(seed, cumulative_kwh=Decimal("0.1")))
    )

    kwh, recorded_at = db_connection.execute(
        select(READINGS.c.cumulative_kwh, READINGS.c.recorded_at)
    ).one()

    assert isinstance(kwh, Decimal)
    assert kwh == Decimal("0.100000")
    assert recorded_at == NOW
    assert recorded_at.utcoffset() is not None
    assert recorded_at.astimezone(UTC).utcoffset().total_seconds() == 0


@pytest.mark.parametrize("attempt", [1, 2])
def test_rows_from_another_test_are_never_visible(
    db_connection: Connection, attempt: int
) -> None:
    """Both runs insert the same email: each sees only its own row (AC-7)."""
    db_connection.execute(insert(USERS).values(user(email="isolated@example.test")))

    count = db_connection.execute(
        select(USERS.c.id).where(USERS.c.email == "isolated@example.test")
    ).all()

    assert len(count) == 1, f"attempt {attempt} saw another test's row"


def test_errors_never_carry_bound_values(db_connection: Connection) -> None:
    """``hide_parameters`` drops bound values from SQLAlchemy's text.

    PostgreSQL's ``DETAIL`` still names the duplicate key value itself, which
    is why IntegrityError text must never be logged (asserted here so the
    limit stays visible).
    """
    secret = "private-owner@example.test"
    db_connection.execute(insert(USERS).values(user(email=secret)))

    with pytest.raises(IntegrityError) as excinfo:
        db_connection.execute(insert(USERS).values(user(email=secret)))

    assert constraint_name(excinfo.value) == "uq_users_email"
    assert "[SQL parameters hidden due to hide_parameters=True]" in str(excinfo.value)
    assert "synthetic-hash" not in str(excinfo.value)
    assert f"Key (email)=({secret})" in str(excinfo.value)
