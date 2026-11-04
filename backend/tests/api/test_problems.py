"""Problem details shape and HTTP error codes: AC-8 and AC-9."""

from collections.abc import Callable
from typing import Any

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from energyiq.platform.http.dependencies import is_json_media_type
from energyiq.platform.http.problems import ERROR_DETAILS, PROBLEM_MEDIA_TYPE

PATH = "/api/v1/consumption/summary"
PROBLEM_KEYS = {"type", "title", "status", "detail", "code", "request_id"}
Body = Callable[..., dict[str, Any]]
JSON = {"Content-Type": "application/json"}


def _assert_problem(
    response: Any, status: int, code: str, extra: set[str] | None = None
) -> dict[str, Any]:
    assert response.status_code == status
    assert response.headers["content-type"] == PROBLEM_MEDIA_TYPE
    problem: dict[str, Any] = response.json()
    assert set(problem) == PROBLEM_KEYS | (extra or set())
    assert problem["type"] == "about:blank"
    assert problem["status"] == status
    assert problem["code"] == code
    assert problem["request_id"] == response.headers["x-request-id"]
    if code in ERROR_DETAILS:
        assert problem["detail"] == ERROR_DETAILS[code]
    return problem


@pytest.mark.parametrize(
    "content",
    [b"", b"{", b'{"meter_id": ', b'{"a": "\xff"}', b"\xff\xfe", b"nul"],
    ids=["empty", "open_brace", "truncated", "bad_utf8_in_string", "bad_utf8", "bare"],
)
def test_malformed_json_is_400(client: TestClient, content: bytes) -> None:
    response = client.post(PATH, content=content, headers=JSON)

    problem = _assert_problem(response, 400, "malformed_json")
    assert problem["title"] == "Bad Request"


def test_unknown_path_is_404(client: TestClient) -> None:
    problem = _assert_problem(client.post("/nope"), 404, "not_found")

    assert problem["title"] == "Not Found"


def test_wrong_method_is_405_and_keeps_allow(client: TestClient) -> None:
    response = client.post("/health")

    _assert_problem(response, 405, "method_not_allowed")
    assert response.headers["allow"] == "GET"
    summary_get = client.get(PATH)
    _assert_problem(summary_get, 405, "method_not_allowed")
    assert summary_get.headers["allow"] == "POST"


@pytest.mark.parametrize(
    "content_type",
    [
        None,
        "text/plain",
        "application/xml",
        "application/json; charset=latin-1",
        "application/json; foo=bar",
        "application/problem+json",
        "multipart/form-data",
    ],
)
def test_non_json_body_is_415(
    client: TestClient, summary_body: Body, content_type: str | None
) -> None:
    headers = {} if content_type is None else {"Content-Type": content_type}

    response = client.post(PATH, content=b'{"meter_id": 1}', headers=headers)

    _assert_problem(response, 415, "unsupported_media_type")


@pytest.mark.parametrize(
    ("content_type", "expected"),
    [
        ("application/json", True),
        ("Application/JSON", True),
        ("application/json; charset=utf-8", True),
        ("application/json;charset=UTF-8", True),
        ('application/json; charset="utf-8"', True),
        ("application/json; charset=utf-8; x=y", False),
        ("application/json; charset", False),
        ("application/jsonx", False),
        ("", False),
        (None, False),
    ],
)
def test_json_media_type_rule(content_type: str | None, expected: bool) -> None:
    assert is_json_media_type(content_type) is expected


def test_404_and_405_win_over_415(client: TestClient) -> None:
    plain = {"Content-Type": "text/plain"}

    assert client.post("/health", content=b"x", headers=plain).status_code == 405
    assert client.post("/nope", content=b"x", headers=plain).status_code == 404


def test_other_http_exception_maps_to_http_status_code(app: FastAPI) -> None:
    @app.get("/teapot")
    def teapot() -> None:
        raise HTTPException(418, detail="secret detail", headers={"X-Extra": "1"})

    response = TestClient(app).get("/teapot")

    problem = _assert_problem(response, 418, "http_418")
    assert problem["detail"] == "I'm a Teapot"
    assert response.headers["x-extra"] == "1"
    assert "secret" not in response.text


def test_unhandled_exception_is_generic_500(app: FastAPI) -> None:
    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("database password is hunter2")

    response = TestClient(app).get("/boom")

    problem = _assert_problem(response, 500, "internal_error")
    assert problem["detail"] == "An unexpected error occurred."
    assert "hunter2" not in response.text
    assert "RuntimeError" not in response.text
