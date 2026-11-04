"""No committed write can split a consumption read (spec 0009/0003 AC-9).

The read takes ``FOR SHARE OF properties, meters`` before it loads the chain,
and every writer that changes what the chain shows takes a conflicting lock.
Each case pauses the read after its readings query, starts the writer, and
waits until ``pg_blocking_pids`` shows the reader's backend blocking another
one. Only then does the read resume. The paused read must equal a read taken
before the write, and a fresh read must show the write.

The one instant writer race moved to ``test_concurrency.py`` (0009/0004 AC-5 c),
where a held meter lock forces the overlap.
"""

import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Event
from typing import Any
from uuid import uuid4

import pytest
from dbsupport import CSRF, PASSWORD
from fastapi.testclient import TestClient
from sqlalchemy import event, text
from sqlalchemy.engine import Connection

from energyiq.main import create_app
from energyiq.platform.settings import Settings

pytestmark = pytest.mark.db_commit

LOCK_WAIT_SECONDS = 10.0
WINDOW = {"from": "2026-11-02T00:00:00Z", "to": "2026-11-04T00:00:00Z"}
MIDDLE = "2026-11-02T12:00:00Z"


@dataclass(frozen=True)
class Chain:
    property_id: str
    meter_id: str
    first_reading_id: str
    event_id: str | None

    @property
    def meter(self) -> str:
        return f"/api/v1/meters/{self.meter_id}"


def _ok(response: Any, status: int = 200) -> Any:
    assert response.status_code == status, response.text
    return response


def _reasons(response: Any) -> list[str | None]:
    _ok(response)
    return [item["reason"] for item in response.json()["intervals"]]


def _correct_reading(client: TestClient, chain: Chain) -> None:
    _ok(
        client.patch(
            f"{chain.meter}/readings/{chain.first_reading_id}",
            json={"status": "voided"},
        )
    )
    for instant, value in (("2026-11-01T12:00:00Z", "0"), (MIDDLE, "50")):
        _ok(
            client.post(
                f"{chain.meter}/readings",
                json={"recorded_at": instant, "cumulative_kwh": value},
            ),
            201,
        )


def _create_event(client: TestClient, chain: Chain) -> None:
    _ok(
        client.post(
            f"{chain.meter}/events",
            json={"event_type": "reset", "effective_at": MIDDLE},
        ),
        201,
    )


def _decide(decision: str) -> Callable[[TestClient, Chain], None]:
    def write(client: TestClient, chain: Chain) -> None:
        _ok(client.post(f"{chain.meter}/events/{chain.event_id}/{decision}"))

    return write


def _update_meter(client: TestClient, chain: Chain) -> None:
    _ok(client.patch(chain.meter, json={"label": "Renamed"}))


def _deactivate_meter(client: TestClient, chain: Chain) -> None:
    _ok(client.post(f"{chain.meter}/deactivate"))


def _update_property(client: TestClient, chain: Chain) -> None:
    _ok(
        client.patch(
            f"/api/v1/properties/{chain.property_id}",
            json={"nickname": "Renamed", "timezone": "UTC"},
        )
    )


def _archive_property(client: TestClient, chain: Chain) -> None:
    _ok(client.delete(f"/api/v1/properties/{chain.property_id}"), 204)


def _changes_reasons(old: Any, new: Any) -> None:
    assert _reasons(new) != _reasons(old)


def _unchanged(old: Any, new: Any) -> None:
    assert _ok(new).json() == old.json()


def _not_found(_old: Any, new: Any) -> None:
    assert new.status_code == 404, new.text


@dataclass(frozen=True)
class Writer:
    write: Callable[[TestClient, Chain], None]
    after: Callable[[Any, Any], None]  # (read before the write, read after it)
    pending_event: bool = False


WRITERS = {
    "reading_void_and_replace": Writer(_correct_reading, _changes_reasons),
    "event_create": Writer(_create_event, _changes_reasons),
    "event_approve": Writer(_decide("approve"), _changes_reasons, pending_event=True),
    "event_reject": Writer(_decide("reject"), _changes_reasons, pending_event=True),
    "meter_update": Writer(_update_meter, _unchanged),
    "meter_deactivate": Writer(_deactivate_meter, _unchanged),
    "property_update": Writer(_update_property, _unchanged),
    "property_archive": Writer(_archive_property, _not_found),
}


def _build_chain(client: TestClient, pending_event: bool) -> Chain:
    home = _ok(client.post("/api/v1/properties", json={"nickname": "Read race"}), 201)
    property_id = home.json()["id"]
    meter = _ok(
        client.post(
            f"/api/v1/properties/{property_id}/meters",
            json={"distributor": "EDESUR", "label": "Main"},
        ),
        201,
    )
    path = f"/api/v1/meters/{meter.json()['id']}"
    first = _ok(
        client.post(
            f"{path}/readings",
            json={"recorded_at": "2026-11-01T12:00:00Z", "cumulative_kwh": "100"},
        ),
        201,
    )
    _ok(
        client.post(
            f"{path}/readings",
            json={"recorded_at": "2026-11-03T12:00:00Z", "cumulative_kwh": "110"},
        ),
        201,
    )
    event_id = None
    if pending_event:
        event_id = _ok(
            client.post(
                f"{path}/events",
                json={"event_type": "reset", "effective_at": MIDDLE},
            ),
            201,
        ).json()["id"]
    return Chain(property_id, meter.json()["id"], first.json()["id"], event_id)


def _blocked_by(poller: Connection, pid: int) -> int:
    """How many backends wait on a lock that ``pid`` holds."""
    return poller.execute(
        text(
            "SELECT count(*) FROM pg_stat_activity"
            " WHERE CAST(:pid AS integer) = ANY(pg_blocking_pids(pid))"
        ),
        {"pid": pid},
    ).scalar_one()


@pytest.mark.parametrize("name", list(WRITERS))
def test_consumption_cannot_mix_a_concurrent_write(
    name: str,
    db_settings: Settings,
    delete_committed_user: Callable[[str, datetime], None],
) -> None:
    writer = WRITERS[name]
    started = datetime.now(UTC)
    email = f"read-race-{uuid4().hex}@example.test"
    app = create_app(db_settings)
    client = TestClient(app, headers=CSRF)
    read_paused = Event()
    resume_read = Event()
    reader_pid: list[int] = []
    try:
        _ok(
            client.post(
                "/api/v1/auth/register", json={"email": email, "password": PASSWORD}
            ),
            201,
        )
        chain = _build_chain(client, writer.pending_event)
        consumption = f"{chain.meter}/consumption"
        before = _ok(client.get(consumption, params=WINDOW))
        cookie = client.cookies.get("energyiq_session")
        assert cookie is not None

        def twin() -> TestClient:
            other = TestClient(app, headers=CSRF)
            other.cookies.set("energyiq_session", cookie)
            return other

        def after_select(
            connection: Connection,
            _cursor: object,
            statement: str,
            _parameters: object,
            _context: object,
            _executemany: bool,
        ) -> None:
            # One shot: only the paused read stops here, never the writer.
            if (
                not read_paused.is_set()
                and "FROM readings" in statement
                and "ORDER BY readings.recorded_at DESC" in statement
            ):
                dbapi = connection.connection.dbapi_connection
                assert dbapi is not None
                reader_pid.append(dbapi.info.backend_pid)
                read_paused.set()
                assert resume_read.wait(timeout=LOCK_WAIT_SECONDS)

        event.listen(app.state.engine, "after_cursor_execute", after_select)
        try:
            with (
                app.state.engine.connect() as raw_poller,
                ThreadPoolExecutor(max_workers=2) as pool,
            ):
                poller = raw_poller.execution_options(isolation_level="AUTOCOMMIT")
                read = pool.submit(lambda: twin().get(consumption, params=WINDOW))
                assert read_paused.wait(timeout=LOCK_WAIT_SECONDS)
                write = pool.submit(writer.write, twin(), chain)
                deadline = time.monotonic() + LOCK_WAIT_SECONDS
                while _blocked_by(poller, reader_pid[0]) == 0:
                    assert not write.done(), "the writer finished during the read"
                    assert time.monotonic() < deadline, "the writer never blocked"
                    time.sleep(0.01)
                resume_read.set()
                during = read.result(timeout=LOCK_WAIT_SECONDS)
                write.result(timeout=LOCK_WAIT_SECONDS)
        finally:
            resume_read.set()
            event.remove(app.state.engine, "after_cursor_execute", after_select)

        assert _ok(during).json() == before.json()
        writer.after(before, client.get(consumption, params=WINDOW))
    finally:
        client.close()
        delete_committed_user(email, started)
