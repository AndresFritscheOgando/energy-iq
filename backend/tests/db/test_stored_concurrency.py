"""A committed correction cannot split a consumption read (spec 0009/0003 AC-9).

The one instant writer race moved to ``test_concurrency.py`` (0009/0004 AC-5 c),
where a held meter lock forces the overlap.
"""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from datetime import UTC, datetime
from threading import Event
from typing import Any
from uuid import uuid4

import pytest
from dbsupport import CSRF, PASSWORD
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.engine import Connection

from energyiq.main import create_app
from energyiq.platform.settings import Settings

pytestmark = pytest.mark.db_commit


def test_consumption_cannot_mix_a_concurrent_correction(
    db_settings: Settings,
    delete_committed_user: Callable[[str, datetime], None],
) -> None:
    started = datetime.now(UTC)
    email = f"read-race-{uuid4().hex}@example.test"
    app = create_app(db_settings)
    client = TestClient(app, headers=CSRF)
    read_paused = Event()
    resume_read = Event()
    writer_at_lock = Event()
    try:
        assert (
            client.post(
                "/api/v1/auth/register", json={"email": email, "password": PASSWORD}
            ).status_code
            == 201
        )
        home = client.post("/api/v1/properties", json={"nickname": "Read race"})
        assert home.status_code == 201
        meter = client.post(
            f"/api/v1/properties/{home.json()['id']}/meters",
            json={"distributor": "EDESUR", "label": "Main"},
        )
        assert meter.status_code == 201
        meter_id = meter.json()["id"]
        path = f"/api/v1/meters/{meter_id}"
        a = client.post(
            f"{path}/readings",
            json={"recorded_at": "2026-11-01T12:00:00Z", "cumulative_kwh": "100"},
        )
        assert a.status_code == 201
        assert (
            client.post(
                f"{path}/readings",
                json={"recorded_at": "2026-11-03T12:00:00Z", "cumulative_kwh": "110"},
            ).status_code
            == 201
        )
        cookie = client.cookies.get("energyiq_session")
        assert cookie is not None

        def after_select(
            _connection: Connection,
            _cursor: object,
            statement: str,
            _parameters: object,
            _context: object,
            _executemany: bool,
        ) -> None:
            if (
                "FROM readings" in statement
                and "ORDER BY readings.recorded_at DESC" in statement
            ):
                read_paused.set()
                assert resume_read.wait(timeout=5)

        def before_lock(
            _connection: Connection,
            _cursor: object,
            statement: str,
            _parameters: object,
            _context: object,
            _executemany: bool,
        ) -> None:
            if "FOR UPDATE OF meters" in statement:
                writer_at_lock.set()

        event.listen(app.state.engine, "after_cursor_execute", after_select)
        event.listen(app.state.engine, "before_cursor_execute", before_lock)
        try:

            def read() -> dict[str, Any]:
                other = TestClient(app, headers=CSRF)
                other.cookies.set("energyiq_session", cookie)
                response = other.get(
                    f"{path}/consumption",
                    params={
                        "from": "2026-11-02T00:00:00Z",
                        "to": "2026-11-04T00:00:00Z",
                    },
                )
                assert response.status_code == 200, response.text
                return response.json()

            def correct() -> None:
                other = TestClient(app, headers=CSRF)
                other.cookies.set("energyiq_session", cookie)
                voided = other.patch(
                    f"{path}/readings/{a.json()['id']}", json={"status": "voided"}
                )
                assert voided.status_code == 200, voided.text
                for instant, value in (
                    ("2026-11-01T12:00:00Z", "0"),
                    ("2026-11-02T12:00:00Z", "50"),
                ):
                    response = other.post(
                        f"{path}/readings",
                        json={"recorded_at": instant, "cumulative_kwh": value},
                    )
                    assert response.status_code == 201, response.text

            with ThreadPoolExecutor(max_workers=2) as pool:
                read_result = pool.submit(read)
                assert read_paused.wait(timeout=5)
                correction = pool.submit(correct)
                assert writer_at_lock.wait(timeout=5)
                with pytest.raises(FutureTimeoutError):
                    correction.result(timeout=0.2)
                resume_read.set()
                old = read_result.result(timeout=5)
                correction.result(timeout=5)
        finally:
            resume_read.set()
            event.remove(app.state.engine, "after_cursor_execute", after_select)
            event.remove(app.state.engine, "before_cursor_execute", before_lock)

        assert old["intervals"][0]["reason"] is None
        assert old["intervals"][0]["consumption_kwh"] == "10.000000"
        new = client.get(
            f"{path}/consumption",
            params={"from": "2026-11-02T00:00:00Z", "to": "2026-11-04T00:00:00Z"},
        )
        assert new.status_code == 200, new.text
        assert [item["reason"] for item in new.json()["intervals"]] == [None, None]
    finally:
        client.close()
        delete_committed_user(email, started)
