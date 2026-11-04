"""Fixtures for the HTTP API tests (spec 0008). Synthetic data only."""

import asyncio
import logging
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.types import Message

from energyiq.identity.dependencies import CurrentUser, get_current_user
from energyiq.main import create_app
from energyiq.platform.http.csrf import CSRF_HEADER
from energyiq.platform.settings import Settings

SUMMARY_PATH = "/api/v1/consumption/summary"
CSRF = {CSRF_HEADER: "1"}
SYNTHETIC_USER = CurrentUser(
    id=UUID("00000000-0000-4000-8000-0000000000aa"), email="owner@example.test"
)


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "ENERGYIQ_ENV",
        "ENERGYIQ_MAX_BODY_BYTES",
        "ENERGYIQ_CORS_ORIGINS",
        "ENERGYIQ_LOG_LEVEL",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def restore_energyiq_loggers() -> Iterator[None]:
    """Undo any level, handler, or propagation change a test makes.

    ``create_app`` configures the process wide ``energyiq`` loggers, so a test
    that sets another level must not leak it, even when its asserts fail.
    """
    saved = [
        (logger, logger.level, list(logger.handlers), logger.propagate)
        for logger in (
            logging.getLogger("energyiq"),
            logging.getLogger("energyiq.access"),
            logging.getLogger("energyiq.errors"),
        )
    ]
    try:
        yield
    finally:
        for logger, level, handlers, propagate in saved:
            logger.setLevel(level)
            logger.handlers[:] = handlers
            logger.propagate = propagate


def signed_in(app: FastAPI) -> FastAPI:
    """Answer ``get_current_user`` with a synthetic user, so tests of the
    stateless summary need no database. Session auth is tested against
    PostgreSQL in ``tests/identity``."""
    app.dependency_overrides[get_current_user] = lambda: SYNTHETIC_USER
    return app


@pytest.fixture
def app() -> FastAPI:
    return signed_in(create_app(Settings(env="test")))


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    """Sends the CSRF header on every request, like the P3 client will."""
    return TestClient(app, headers=CSRF)


class _ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def log_records(app: FastAPI) -> Iterator[list[logging.LogRecord]]:
    """Records reaching the ``energyiq`` logger tree during the test."""
    handler = _ListHandler()
    logger = logging.getLogger("energyiq")
    logger.addHandler(handler)
    try:
        yield handler.records
    finally:
        logger.removeHandler(handler)


def access_records(records: Sequence[logging.LogRecord]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for record in records:
        if record.name == "energyiq.access":
            found.append(cast("dict[str, Any]", record.__dict__["access"]))
    return found


@pytest.fixture
def access() -> Callable[[Sequence[logging.LogRecord]], list[dict[str, Any]]]:
    return access_records


@pytest.fixture
def meter_id() -> UUID:
    return UUID("00000000-0000-4000-8000-000000000001")


def _reading(
    recorded_at: str,
    kwh: str,
    status: str | None = None,
    reading_id: UUID | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "id": str(reading_id or uuid4()),
        "recorded_at": recorded_at,
        "cumulative_kwh": kwh,
    }
    if status is not None:
        item["status"] = status
    return item


@pytest.fixture
def reading() -> Callable[..., dict[str, Any]]:
    """Build one reading JSON object: ``reading(recorded_at, kwh, status=...)``."""
    return _reading


@pytest.fixture
def summary_body(meter_id: UUID) -> Callable[..., dict[str, Any]]:
    """Build a request body with a default 3 day October window."""

    def build(
        readings: list[dict[str, Any]],
        events: list[dict[str, Any]] | None = None,
        start: str = "2026-10-01T00:00:00Z",
        end: str = "2026-10-04T00:00:00Z",
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "meter_id": str(meter_id),
            "window": {"start": start, "end": end},
            "readings": readings,
        }
        if events is not None:
            body["events"] = events
        return body

    return build


@dataclass
class RawResponse:
    status: int
    headers: dict[str, str]
    body: bytes
    messages: list[Message]


def _raw_call(
    app: FastAPI,
    method: str,
    path: str,
    headers: Sequence[tuple[str, str]] = (),
    chunks: Sequence[bytes] = (),
    disconnect_first: bool = False,
    csrf: bool = True,
) -> RawResponse:
    """Drive the ASGI app directly, for headers and bodies a client normalizes.

    The CSRF header is added unless ``csrf=False``.
    """
    if csrf:
        headers = [(CSRF_HEADER, "1"), *headers]

    async def run() -> RawResponse:
        incoming: list[Message] = (
            [{"type": "http.disconnect"}]
            if disconnect_first
            else [
                {
                    "type": "http.request",
                    "body": chunk,
                    "more_body": index < len(chunks) - 1,
                }
                for index, chunk in enumerate(chunks or [b""])
            ]
        )
        sent: list[Message] = []

        async def receive() -> Message:
            if incoming:
                return incoming.pop(0)
            await asyncio.sleep(0)
            return {"type": "http.disconnect"}

        async def send(message: Message) -> None:
            sent.append(message)

        scope: dict[str, Any] = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.4"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "root_path": "",
            "headers": [(k.lower().encode(), v.encode()) for k, v in headers],
            "client": ("127.0.0.1", 50000),
            "server": ("testserver", 80),
        }
        await app(scope, receive, send)
        start = next((m for m in sent if m["type"] == "http.response.start"), None)
        return RawResponse(
            status=start["status"] if start else 0,
            headers={
                k.decode().lower(): v.decode()
                for k, v in (start or {}).get("headers", [])
            },
            body=b"".join(
                m.get("body", b"") for m in sent if m["type"] == "http.response.body"
            ),
            messages=sent,
        )

    return asyncio.run(run())


@pytest.fixture
def raw_call() -> Callable[..., RawResponse]:
    return _raw_call
