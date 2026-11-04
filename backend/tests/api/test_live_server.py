"""Live smoke test: the documented uvicorn command serves requests (AC-1, AC-13)."""

import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import httpx2
import pytest

from energyiq import __version__

ROOT = Path(__file__).parents[3]


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _stop(process: subprocess.Popen[bytes]) -> None:
    """Terminate the server, and kill it if it ignores the request."""
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


@pytest.fixture
def live_client(tmp_path: Path) -> Iterator[httpx2.Client]:
    """An httpx2 client for the documented uvicorn command on a free port.

    The client ignores proxy environment variables (``trust_env=False``) so
    it always talks to the local server. Teardown stops the server, kills it
    if needed, and closes the client and the log file even when a step fails.
    """
    port = _free_port()
    log_path = tmp_path / "server.log"
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "energyiq.main:create_app",
                "--factory",
                "--app-dir",
                "backend/src",
                "--no-access-log",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            cwd=ROOT,
            stdout=log,
            stderr=subprocess.STDOUT,
            env={**os.environ, "ENERGYIQ_ENV": "test"},
        )
        try:
            with httpx2.Client(
                base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=10
            ) as client:
                deadline = time.monotonic() + 20
                while True:
                    if process.poll() is not None:
                        log.flush()
                        pytest.fail(log_path.read_text(encoding="utf-8"))
                    try:
                        client.get("/health", timeout=0.5)
                        break
                    except httpx2.TransportError:
                        if time.monotonic() > deadline:
                            pytest.fail("uvicorn did not start within 20 seconds")
                        time.sleep(0.1)
                yield client
        finally:
            _stop(process)


def test_live_server_answers_health_and_summary(live_client: httpx2.Client) -> None:
    health = live_client.get("/health")
    summary = live_client.post(
        "/api/v1/consumption/summary",
        json={
            "meter_id": str(uuid4()),
            "window": {"start": "2026-10-01T00:00:00Z", "end": "2026-10-03T00:00:00Z"},
            "readings": [
                {
                    "id": str(uuid4()),
                    "recorded_at": "2026-10-01T00:00:00Z",
                    "cumulative_kwh": "100",
                },
                {
                    "id": str(uuid4()),
                    "recorded_at": "2026-10-02T00:00:00Z",
                    "cumulative_kwh": "112.5",
                },
            ],
        },
    )

    assert health.status_code == 200
    assert health.json() == {"status": "ok", "version": __version__}
    assert summary.status_code == 200
    assert summary.json()["measured_kwh"] == "12.5"
    assert summary.json()["coverage_ratio"] == "0.5000"
    assert "x-request-id" in summary.headers
