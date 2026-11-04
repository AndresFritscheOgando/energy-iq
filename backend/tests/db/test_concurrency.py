"""Duplicate and concurrent requests with committed transactions (spec 0009/0004 AC-5).

Savepoint isolation hides unique index races and retry key waits, so these
tests commit for real (``committed_db`` truncates as the migrator before and
after). Overlap is forced, never left to timing: a third connection holds the
contested row, both requests start, the test waits until
``pg_stat_activity`` shows both blocked on a lock, and only then releases it.
"""

import json
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import pytest
from dbsupport import CSRF, PASSWORD
from fastapi import FastAPI
from fastapi.testclient import TestClient
from routesupport import api_routes
from sqlalchemy import Connection, Engine, text

from energyiq.main import create_app
from energyiq.platform.settings import Settings

COOKIE = "energyiq_session"
V1 = "/api/v1"
PAST = "2026-01-01T12:00:00Z"
LOCK_WAIT_SECONDS = 10.0


@dataclass(frozen=True)
class Reply:
    status: int
    body: bytes
    headers: dict[str, str]

    def json(self) -> Any:
        return json.loads(self.body)


def _reply(response: Any) -> Reply:
    return Reply(response.status_code, response.content, dict(response.headers))


@dataclass(frozen=True)
class Owner:
    app: FastAPI
    client: TestClient
    user_id: str
    property_id: str
    meter_id: str

    def twin(self) -> TestClient:
        """Another client over the same app, signed in with the same session."""
        other = TestClient(self.app, headers=CSRF)
        other.cookies.set(COOKIE, self.client.cookies[COOKIE])
        return other


def _created(response: Any) -> str:
    assert response.status_code == 201, response.text
    return response.json()["id"]


@pytest.fixture
def app(committed_db: Engine, db_settings: Settings) -> FastAPI:
    return create_app(db_settings)


@pytest.fixture
def owner(app: FastAPI) -> Owner:
    client = TestClient(app, headers=CSRF)
    user_id = _created(
        client.post(
            f"{V1}/auth/register",
            json={
                "email": f"race-{uuid4().hex[:8]}@example.test",
                "password": PASSWORD,
            },
        )
    )
    property_id = _created(client.post(f"{V1}/properties", json={"nickname": "Race"}))
    meter_id = _created(
        client.post(
            f"{V1}/properties/{property_id}/meters",
            json={"distributor": "EDESUR", "label": "Main"},
        )
    )
    return Owner(app, client, user_id, property_id, meter_id)


def _count(engine: Engine, sql: str, params: dict[str, object] | None = None) -> Any:
    with engine.connect() as connection:
        return connection.execute(text(sql), params or {}).scalar_one()


def _lock_waiters(poller: Connection) -> int:
    return poller.execute(
        text(
            "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()"
            " AND wait_event_type = 'Lock' AND pid <> pg_backend_pid()"
        )
    ).scalar_one()


def overlapped[T](
    engine: Engine, hold: Callable[[Connection], None], calls: Sequence[Callable[[], T]]
) -> list[T]:
    """Run ``calls`` in threads while ``hold`` keeps a lock in an open
    transaction; release it only once every call is blocked on a lock."""
    with engine.connect() as holder, engine.connect() as raw_poller:
        poller = raw_poller.execution_options(isolation_level="AUTOCOMMIT")
        transaction = holder.begin()
        released = False
        try:
            hold(holder)
            with ThreadPoolExecutor(max_workers=len(calls)) as pool:
                futures = [pool.submit(call) for call in calls]
                try:
                    deadline = time.monotonic() + LOCK_WAIT_SECONDS
                    while (waiting := _lock_waiters(poller)) < len(calls):
                        assert time.monotonic() < deadline, (
                            f"only {waiting} of {len(calls)} requests blocked on a lock"
                        )
                        time.sleep(0.01)
                finally:
                    transaction.rollback()
                    released = True
                return [future.result(timeout=LOCK_WAIT_SECONDS) for future in futures]
        finally:
            if not released:
                transaction.rollback()


def _hold_meter(meter_id: str) -> Callable[[Connection], None]:
    def hold(connection: Connection) -> None:
        connection.execute(
            text("SELECT id FROM meters WHERE id = :id FOR UPDATE"), {"id": meter_id}
        )

    return hold


# (a) the same key and body twice, sequentially, for every idempotent route ---


@dataclass(frozen=True)
class Replayable:
    """How to call one idempotent route, and what one real write leaves."""

    prepare: Callable[[Owner], tuple[str, dict[str, Any] | None]]
    action: str
    table: str | None  # the table that gains exactly one row, if any


def _event(owner: Owner) -> str:
    return _created(
        owner.client.post(
            f"{V1}/meters/{owner.meter_id}/events",
            json={"event_type": "reset", "effective_at": PAST},
        )
    )


IDEMPOTENT: dict[tuple[str, str], Replayable] = {
    ("POST", f"{V1}/properties"): Replayable(
        lambda o: (f"{V1}/properties", {"nickname": "Replayed"}),
        "property.create",
        "properties",
    ),
    ("POST", f"{V1}/properties/{{property_id}}/meters"): Replayable(
        lambda o: (
            f"{V1}/properties/{o.property_id}/meters",
            {"distributor": "EDESUR", "label": "Second"},
        ),
        "meter.create",
        "meters",
    ),
    ("POST", f"{V1}/meters/{{meter_id}}/deactivate"): Replayable(
        lambda o: (f"{V1}/meters/{o.meter_id}/deactivate", None),
        "meter.deactivate",
        None,
    ),
    ("POST", f"{V1}/meters/{{meter_id}}/readings"): Replayable(
        lambda o: (
            f"{V1}/meters/{o.meter_id}/readings",
            {"recorded_at": PAST, "cumulative_kwh": "12.5"},
        ),
        "reading.create",
        "readings",
    ),
    ("POST", f"{V1}/meters/{{meter_id}}/events"): Replayable(
        lambda o: (
            f"{V1}/meters/{o.meter_id}/events",
            {"event_type": "calibration", "effective_at": PAST},
        ),
        "event.create",
        "meter_events",
    ),
    ("POST", f"{V1}/meters/{{meter_id}}/events/{{event_id}}/approve"): Replayable(
        lambda o: (f"{V1}/meters/{o.meter_id}/events/{_event(o)}/approve", None),
        "event.approve",
        None,
    ),
    ("POST", f"{V1}/meters/{{meter_id}}/events/{{event_id}}/reject"): Replayable(
        lambda o: (f"{V1}/meters/{o.meter_id}/events/{_event(o)}/reject", None),
        "event.reject",
        None,
    ),
}


def test_every_idempotent_route_is_in_the_replay_matrix() -> None:
    served = {
        route.key
        for route in api_routes(create_app(Settings(env="test")))
        if "idempotent" in route.calls
    }

    assert served == set(IDEMPOTENT)


@pytest.mark.db_commit
@pytest.mark.parametrize("key", list(IDEMPOTENT), ids=" ".join)
def test_a_sequential_retry_replays_the_first_response(
    committed_db: Engine, owner: Owner, key: tuple[str, str]
) -> None:
    route = IDEMPOTENT[key]
    path, body = route.prepare(owner)
    rows = f"SELECT count(*) FROM {route.table}" if route.table else "SELECT 0"
    rows_before = _count(committed_db, rows)
    audits = "SELECT count(*) FROM audit_events WHERE action = :action"
    audits_before = _count(committed_db, audits, {"action": route.action})
    headers = {"Idempotency-Key": f"replay-{uuid4().hex}"}

    first = _reply(owner.client.post(path, json=body, headers=headers))
    second = _reply(owner.client.post(path, json=body, headers=headers))

    assert 200 <= first.status < 300, first.body
    assert (second.status, second.body) == (first.status, first.body)
    assert "idempotent-replayed" not in first.headers
    assert second.headers["idempotent-replayed"] == "true"
    assert _count(committed_db, rows) == rows_before + (1 if route.table else 0)
    assert _count(committed_db, audits, {"action": route.action}) == audits_before + 1
    assert _count(committed_db, "SELECT count(*) FROM idempotency_keys") == 1


# (b) the same key from two threads at once -----------------------------------


@pytest.mark.db_commit
def test_one_key_from_two_threads_writes_once(
    committed_db: Engine, owner: Owner
) -> None:
    key = f"twin-{uuid4().hex}"
    path = f"{V1}/meters/{owner.meter_id}/readings"
    body = {"recorded_at": PAST, "cumulative_kwh": "40"}

    def hold(connection: Connection) -> None:
        connection.execute(
            text(
                "INSERT INTO idempotency_keys (user_id, key, operation, request_hash,"
                " created_at, expires_at) VALUES (:user, :key, 'held by the test',"
                " sha256(''::bytea), now(), now() + interval '1 hour')"
            ),
            {"user": owner.user_id, "key": key},
        )

    def post() -> Reply:
        return _reply(
            owner.twin().post(path, json=body, headers={"Idempotency-Key": key})
        )

    first, second = overlapped(committed_db, hold, [post, post])

    assert first.status == second.status == 201
    assert first.body == second.body
    replayed = sorted(
        str(r.headers.get("idempotent-replayed")) for r in (first, second)
    )
    assert replayed == ["None", "true"]
    assert _count(committed_db, "SELECT count(*) FROM readings") == 1
    audits = "SELECT count(*) FROM audit_events WHERE action = 'reading.create'"
    assert _count(committed_db, audits) == 1
    assert _count(committed_db, "SELECT count(*) FROM idempotency_keys") == 1


# (c) two identical reading POSTs without a key -------------------------------


@pytest.mark.db_commit
def test_two_writers_at_one_instant_have_one_winner(
    committed_db: Engine, owner: Owner
) -> None:
    path = f"{V1}/meters/{owner.meter_id}/readings"

    def post(value: str) -> Callable[[], Reply]:
        return lambda: _reply(
            owner.twin().post(path, json={"recorded_at": PAST, "cumulative_kwh": value})
        )

    results = overlapped(
        committed_db, _hold_meter(owner.meter_id), [post("10"), post("10")]
    )

    assert sorted(reply.status for reply in results) == [201, 409]
    winner = next(reply.json() for reply in results if reply.status == 201)
    loser = next(reply.json() for reply in results if reply.status == 409)
    assert loser["code"] == "reading_exists_at_instant"
    assert loser["existing_reading_id"] == winner["id"]
    assert _count(committed_db, "SELECT count(*) FROM readings") == 1
    audits = "SELECT count(*) FROM audit_events WHERE action = 'reading.create'"
    assert _count(committed_db, audits) == 1


# (d) concurrent registration of one email ------------------------------------


@pytest.mark.db_commit
@pytest.mark.parametrize(
    "hosts",
    [("10.0.0.1", "10.0.0.1"), ("10.0.0.1", "10.0.0.2")],
    ids=["one client (advisory lock)", "two clients (unique index)"],
)
def test_one_email_registered_twice_at_once(
    committed_db: Engine, app: FastAPI, hosts: tuple[str, str]
) -> None:
    email = f"twin-{uuid4().hex[:8]}@example.test"

    def hold(connection: Connection) -> None:
        connection.execute(
            text(
                "INSERT INTO users (id, email, password_hash, created_at)"
                " VALUES (:id, :email, 'held by the test', now())"
            ),
            {"id": uuid4(), "email": email},
        )

    def register(host: str) -> Callable[[], Reply]:
        def call() -> Reply:
            client = TestClient(app, headers=CSRF, client=(host, 50000))
            return _reply(
                client.post(
                    f"{V1}/auth/register", json={"email": email, "password": PASSWORD}
                )
            )

        return call

    results = overlapped(committed_db, hold, [register(host) for host in hosts])

    assert sorted(reply.status for reply in results) == [201, 409]
    loser = next(reply.json() for reply in results if reply.status == 409)
    assert loser["code"] == "email_taken"
    assert _count(committed_db, "SELECT count(*) FROM users") == 1
    assert _count(committed_db, "SELECT count(*) FROM sessions") == 1
    outcomes = (
        "SELECT count(*) FROM audit_events WHERE action = 'auth.register'"
        " AND metadata ->> 'outcome' = 'email_taken'"
    )
    assert _count(committed_db, outcomes) == 1


# (e) concurrent status changes on one reading --------------------------------


@pytest.mark.db_commit
@pytest.mark.parametrize(
    "targets",
    [("flagged", "flagged"), ("flagged", "voided"), ("voided", "voided")],
    ids="-".join,
)
def test_concurrent_status_changes_stay_consistent(
    committed_db: Engine, owner: Owner, targets: tuple[str, str]
) -> None:
    reading = _created(
        owner.client.post(
            f"{V1}/meters/{owner.meter_id}/readings",
            json={"recorded_at": PAST, "cumulative_kwh": "7"},
        )
    )
    path = f"{V1}/meters/{owner.meter_id}/readings/{reading}"

    def patch(status: str) -> Callable[[], Reply]:
        return lambda: _reply(owner.twin().patch(path, json={"status": status}))

    results = overlapped(
        committed_db, _hold_meter(owner.meter_id), [patch(target) for target in targets]
    )

    final = _count(
        committed_db, "SELECT status FROM readings WHERE id = :id", {"id": reading}
    )
    with committed_db.connect() as connection:
        transitions = [
            (row.old, row.new)
            for row in connection.execute(
                text(
                    "SELECT metadata ->> 'from' AS old, metadata ->> 'to' AS new"
                    " FROM audit_events WHERE action = 'reading.status_change'"
                    " AND entity_id = :id ORDER BY id"
                ),
                {"id": reading},
            )
        ]
    # One audit row per real transition, chained from the created state.
    state = "valid"
    for old, new in transitions:
        assert old == state and new != old
        state = new
    assert state == final
    assert final in targets
    succeeded = [reply for reply in results if reply.status == 200]
    rejected = [reply for reply in results if reply.status != 200]
    assert all(reply.json()["status"] in targets for reply in succeeded)
    for reply in rejected:
        assert reply.status == 409 and reply.json()["code"] == "reading_voided"
    # A no op change succeeds without an audit row, so transitions never
    # exceed the distinct successful targets.
    assert len(transitions) == len({reply.json()["status"] for reply in succeeded})
