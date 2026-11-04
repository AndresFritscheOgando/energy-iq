"""Request context, access log, body limits, and the 500 path: AC-8 to AC-10."""

import json
import logging
import re
from collections.abc import Callable, Iterator, Sequence
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from energyiq.main import create_app
from energyiq.platform.logging import JsonFormatter
from energyiq.platform.settings import Settings

PATH = "/api/v1/consumption/summary"
UUID4 = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
)
ACCESS_KEYS = {
    "timestamp",
    "level",
    "request_id",
    "method",
    "route",
    "status",
    "duration_ms",
}
Records = list[logging.LogRecord]
Access = Callable[[Sequence[logging.LogRecord]], list[dict[str, Any]]]
Body = Callable[..., dict[str, Any]]
Raw = Callable[..., Any]
JSON = {"Content-Type": "application/json"}


@pytest.mark.parametrize("value", ["abc-123", "A" * 64, "0"])
def test_valid_client_request_id_is_echoed(client: TestClient, value: str) -> None:
    response = client.get("/health", headers={"X-Request-ID": value})

    assert response.headers["x-request-id"] == value


@pytest.mark.parametrize("value", ["bad id!", "A" * 65, "", "a_b", "ünï"])
def test_invalid_client_request_id_is_replaced(client: TestClient, value: str) -> None:
    response = client.get("/health", headers={"X-Request-ID": value.encode()})  # pyright: ignore[reportArgumentType]

    assert UUID4.fullmatch(response.headers["x-request-id"])


def test_problem_request_id_matches_header(client: TestClient) -> None:
    response = client.get("/nope", headers={"X-Request-ID": "trace-1"})

    assert response.json()["request_id"] == "trace-1"
    assert response.headers["x-request-id"] == "trace-1"


def test_one_access_line_with_exactly_seven_keys(
    client: TestClient, log_records: Records, summary_body: Body
) -> None:
    client.post(
        PATH + "?token=SECRET-QUERY",
        json=summary_body([]),
        headers={"X-Request-ID": "trace-2", "Authorization": "SECRET-HEADER"},
    )

    access = [r for r in log_records if r.name == "energyiq.access"]
    assert len(access) == 1
    line = json.loads(JsonFormatter().format(access[0]))
    assert set(line) == ACCESS_KEYS
    assert line["level"] == "INFO"
    assert line["request_id"] == "trace-2"
    assert line["method"] == "POST"
    assert line["route"] == "/api/v1/consumption/summary"
    assert line["status"] == 200
    assert isinstance(line["duration_ms"], float)
    assert line["timestamp"].endswith("Z")
    text = JsonFormatter().format(access[0])
    for secret in ("SECRET", "meter_id", "127.0.0.1", "testclient"):
        assert secret not in text


@pytest.mark.parametrize(
    ("method", "path", "route", "status"),
    [
        ("GET", "/health", "/health", 200),
        ("GET", "/nope", "unmatched", 404),
        ("GET", "/docs", "unmatched", 200),
        ("GET", "/openapi.json", "unmatched", 200),
    ],
)
def test_access_route_template(
    client: TestClient,
    log_records: Records,
    access: Access,
    method: str,
    path: str,
    route: str,
    status: int,
) -> None:
    client.request(method, path)

    assert [(a["route"], a["status"]) for a in access(log_records)] == [(route, status)]


def test_repeated_create_app_never_duplicates_handlers(
    log_records: Records, access: Access
) -> None:
    for _ in range(3):
        create_app(Settings(env="test"))
    root = logging.getLogger("energyiq")
    json_handlers = [h for h in root.handlers if h.get_name() == "energyiq-json"]

    TestClient(create_app(Settings(env="test"))).get("/health")

    assert len(json_handlers) == 1
    assert len(access(log_records)) == 1


def test_access_line_written_at_warning_level(
    log_records: Records, access: Access
) -> None:
    TestClient(create_app(Settings(env="test", log_level="WARNING"))).get("/health")

    assert len(access(log_records)) == 1
    assert logging.getLogger("energyiq").level == logging.WARNING


def test_unhandled_exception_logs_one_traceback_with_request_id(
    app: FastAPI, log_records: Records, access: Access
) -> None:
    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("kaboom")

    response = TestClient(app).get("/boom", headers={"X-Request-ID": "trace-500"})

    assert response.status_code == 500
    assert response.headers["x-request-id"] == "trace-500"
    errors = [r for r in log_records if r.name == "energyiq.errors"]
    assert len(errors) == 1
    line = json.loads(JsonFormatter().format(errors[0]))
    assert line["request_id"] == "trace-500"
    assert "RuntimeError: kaboom" in line["traceback"]
    assert [(a["status"], a["route"]) for a in access(log_records)] == [(500, "/boom")]


def test_500_from_a_dependency_carries_no_cors_headers(
    app: FastAPI, summary_body: Body
) -> None:
    from energyiq.platform.clock import get_now

    def broken_clock() -> None:
        raise RuntimeError("clock broke")

    app.dependency_overrides[get_now] = broken_clock

    response = TestClient(app).post(
        PATH, json=summary_body([]), headers={"Origin": "http://localhost:3000"}
    )

    assert response.status_code == 500
    assert response.json()["code"] == "internal_error"
    assert "access-control-allow-origin" not in response.headers
    assert "x-request-id" in response.headers


def test_error_after_response_started_sends_nothing_more(
    app: FastAPI, raw_call: Raw, log_records: Records, access: Access
) -> None:
    def chunks() -> Iterator[bytes]:
        yield b"first"
        raise RuntimeError("mid stream")

    @app.get("/stream")
    def stream() -> StreamingResponse:
        return StreamingResponse(chunks())

    result = raw_call(app, "GET", "/stream")

    assert result.status == 200
    assert result.body == b"first"
    assert [m["type"] for m in result.messages].count("http.response.start") == 1
    assert not any(b"internal_error" in m.get("body", b"") for m in result.messages)
    assert len([r for r in log_records if r.name == "energyiq.errors"]) == 1
    assert [a["status"] for a in access(log_records)] == [200]


def test_client_disconnect_before_response_logs_499(
    app: FastAPI, raw_call: Raw, log_records: Records, access: Access
) -> None:
    result = raw_call(
        app,
        "POST",
        PATH,
        headers=[("content-type", "application/json")],
        disconnect_first=True,
    )

    assert result.messages == []
    assert [a["status"] for a in access(log_records)] == [499]


def test_declared_body_over_cap_is_413_before_reading(
    client: TestClient, log_records: Records, access: Access
) -> None:
    response = client.post(PATH, content=b"x" * (2 * 1024 * 1024), headers=JSON)

    assert response.status_code == 413
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "payload_too_large"
    assert "x-request-id" in response.headers
    assert [(a["status"], a["route"]) for a in access(log_records)] == [
        (413, "unmatched")
    ]


def test_streamed_body_over_cap_is_413_not_400(app: FastAPI, raw_call: Raw) -> None:
    chunk = b"x" * (256 * 1024)

    result = raw_call(
        app,
        "POST",
        PATH,
        headers=[("content-type", "application/json")],
        chunks=[chunk] * 8,
    )

    assert result.status == 413
    assert json.loads(result.body)["code"] == "payload_too_large"
    assert "x-request-id" in result.headers


def test_streamed_body_under_cap_is_processed(
    app: FastAPI, raw_call: Raw, summary_body: Body
) -> None:
    payload = json.dumps(summary_body([])).encode()
    middle = len(payload) // 2

    result = raw_call(
        app,
        "POST",
        PATH,
        headers=[("content-type", "application/json")],
        chunks=[payload[:middle], payload[middle:]],
    )

    assert result.status == 200


def test_body_cap_comes_from_settings(summary_body: Body) -> None:
    client = TestClient(create_app(Settings(env="test", max_body_bytes=10)))

    assert client.post(PATH, json=summary_body([])).status_code == 413


@pytest.mark.parametrize("value", ["abc", "-1", "1.5", "1e3", ""])
def test_invalid_content_length_is_400(app: FastAPI, raw_call: Raw, value: str) -> None:
    result = raw_call(
        app,
        "POST",
        PATH,
        headers=[("content-type", "application/json"), ("content-length", value)],
        chunks=[b"{}"],
    )

    assert result.status == 400
    assert result.headers["content-type"] == "application/problem+json"
    assert json.loads(result.body)["code"] == "invalid_content_length"
    assert "x-request-id" in result.headers


def test_413_and_415_carry_request_id(client: TestClient) -> None:
    too_big = client.post(
        PATH, content=b"x" * 2_000_000, headers={**JSON, "X-Request-ID": "big-1"}
    )
    not_json = client.post(
        PATH,
        content=b"x",
        headers={"Content-Type": "text/plain", "X-Request-ID": "txt-1"},
    )

    assert too_big.headers["x-request-id"] == "big-1"
    assert too_big.json()["request_id"] == "big-1"
    assert not_json.headers["x-request-id"] == "txt-1"
    assert not_json.json()["request_id"] == "txt-1"
