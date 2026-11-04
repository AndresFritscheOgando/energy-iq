"""Request validation: AC-4, AC-5 and the validation side of AC-8."""

from collections.abc import Callable
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from energyiq.platform.http.problems import VALIDATION_MESSAGES

PATH = "/api/v1/consumption/summary"
Body = Callable[..., dict[str, Any]]
ReadingFactory = Callable[..., dict[str, Any]]


def _errors(client: TestClient, body: object) -> list[dict[str, Any]]:
    response = client.post(PATH, json=body)
    assert response.status_code == 422, response.text
    assert response.headers["content-type"] == "application/problem+json"
    problem = response.json()
    assert problem["code"] == "validation_error"
    assert problem["detail"] == "The request body failed validation."
    errors: list[dict[str, Any]] = problem["errors"]
    for item in errors:
        assert set(item) == {"loc", "code", "message"}
        assert item["message"] == VALIDATION_MESSAGES[item["code"]]
    return errors


def _one_reading(
    summary_body: Body, reading: ReadingFactory, **overrides: object
) -> dict[str, Any]:
    item = reading("2026-10-01T16:00:00Z", "1")
    item.update(overrides)
    return summary_body([item])


@pytest.mark.parametrize(
    ("value", "code"),
    [
        (13049.0, "invalid_type"),
        (13049, "invalid_type"),
        ("1E+2", "invalid_kwh"),
        ("1.0000000", "invalid_kwh"),
        ("9999999999999", "invalid_kwh"),
        ("-1", "invalid_kwh"),
        ("+1", "invalid_kwh"),
        ("NaN", "invalid_kwh"),
        ("", "invalid_kwh"),
        (" 1", "invalid_kwh"),
        ("1\n", "invalid_kwh"),
        ("1.", "invalid_kwh"),
        (".5", "invalid_kwh"),
        (None, "invalid_type"),
    ],
)
def test_bad_cumulative_kwh_is_located(
    client: TestClient,
    summary_body: Body,
    reading: ReadingFactory,
    value: object,
    code: str,
) -> None:
    body = _one_reading(summary_body, reading, cumulative_kwh=value)

    assert _errors(client, body) == [
        {
            "loc": ["body", "readings", 0, "cumulative_kwh"],
            "code": code,
            "message": VALIDATION_MESSAGES[code],
        }
    ]


@pytest.mark.parametrize("value", ["0", "999999999999.999999", "13049.0", "0.000001"])
def test_good_cumulative_kwh_is_accepted(
    client: TestClient, summary_body: Body, reading: ReadingFactory, value: str
) -> None:
    body = _one_reading(summary_body, reading, cumulative_kwh=value)

    assert client.post(PATH, json=body).status_code == 200


@pytest.mark.parametrize(
    ("value", "code"),
    [
        (1700000000, "invalid_type"),
        ("1700000000", "invalid_datetime"),
        ("2026-10-01T16:00:00", "invalid_datetime"),
        ("2026-10-01", "invalid_datetime"),
        ("not a date", "invalid_datetime"),
        ("9999-12-31T23:00:00-04:00", "datetime_out_of_range"),
        ("0001-01-01T00:00:00+04:00", "datetime_out_of_range"),
    ],
)
def test_bad_recorded_at_is_located(
    client: TestClient,
    summary_body: Body,
    reading: ReadingFactory,
    value: object,
    code: str,
) -> None:
    body = _one_reading(summary_body, reading, recorded_at=value)

    assert _errors(client, body) == [
        {
            "loc": ["body", "readings", 0, "recorded_at"],
            "code": code,
            "message": VALIDATION_MESSAGES[code],
        }
    ]


@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("2026-10-02T00:00:00Z", "2026-10-01T00:00:00Z"),
        ("2026-10-01T00:00:00Z", "2026-10-01T00:00:00Z"),
        ("2026-10-01T04:00:00Z", "2026-10-01T00:00:00-04:00"),
    ],
)
def test_window_end_must_be_after_start(
    client: TestClient, summary_body: Body, start: str, end: str
) -> None:
    body = summary_body([], start=start, end=end)

    assert _errors(client, body) == [
        {
            "loc": ["body", "window"],
            "code": "window_order",
            "message": VALIDATION_MESSAGES["window_order"],
        }
    ]


@pytest.mark.parametrize(
    ("path", "body_update"),
    [
        (["body", "extra"], {"extra": 1}),
        (
            ["body", "window", "zone"],
            {
                "window": {
                    "start": "2026-10-01T00:00:00Z",
                    "end": "2026-10-02T00:00:00Z",
                    "zone": "x",
                }
            },
        ),
    ],
)
def test_unknown_fields_are_rejected(
    client: TestClient,
    summary_body: Body,
    path: list[object],
    body_update: dict[str, Any],
) -> None:
    body = {**summary_body([]), **body_update}

    assert _errors(client, body) == [
        {"loc": path, "code": "unknown_field", "message": "Field is not allowed."}
    ]


@pytest.mark.parametrize(
    "field", ["created_at", "meter_id", "note", "source_ref", "original_local_date"]
)
def test_server_owned_and_unsupported_reading_fields_are_rejected(
    client: TestClient, summary_body: Body, reading: ReadingFactory, field: str
) -> None:
    body = _one_reading(summary_body, reading, **{field: "2026-10-01T00:00:00Z"})

    assert _errors(client, body) == [
        {
            "loc": ["body", "readings", 0, field],
            "code": "unknown_field",
            "message": "Field is not allowed.",
        }
    ]


def test_event_created_at_is_rejected(client: TestClient, summary_body: Body) -> None:
    event = {
        "id": str(uuid4()),
        "event_type": "reset",
        "effective_at": "2026-10-01T00:00:00Z",
        "created_at": "2026-10-01T00:00:00Z",
    }

    errors = _errors(client, summary_body([], events=[event]))

    assert [(e["loc"], e["code"]) for e in errors] == [
        (["body", "events", 0, "created_at"], "unknown_field")
    ]


@pytest.mark.parametrize(
    "approval",
    [
        {"approved_by": "00000000-0000-4000-8000-00000000000a"},
        {"approved_at": "2026-10-01T00:00:00Z"},
    ],
)
def test_approval_fields_come_together(
    client: TestClient, summary_body: Body, approval: dict[str, str]
) -> None:
    event = {
        "id": str(uuid4()),
        "event_type": "reset",
        "effective_at": "2026-10-01T00:00:00Z",
        **approval,
    }

    assert _errors(client, summary_body([], events=[event])) == [
        {
            "loc": ["body", "events", 0],
            "code": "approval_pair",
            "message": VALIDATION_MESSAGES["approval_pair"],
        }
    ]


def test_list_caps(
    client: TestClient, summary_body: Body, reading: ReadingFactory
) -> None:
    too_many_readings = summary_body([reading("2026-10-01T16:00:00Z", "1")] * 5_001)
    event = {
        "id": str(uuid4()),
        "event_type": "reset",
        "effective_at": "2026-10-01T00:00:00Z",
    }
    too_many_events = summary_body([], events=[event] * 501)

    assert _errors(client, too_many_readings) == [
        {
            "loc": ["body", "readings"],
            "code": "too_many_items",
            "message": "List exceeds its maximum length.",
        }
    ]
    assert [e["loc"] for e in _errors(client, too_many_events)] == [["body", "events"]]


@pytest.mark.parametrize(
    ("update", "loc", "code"),
    [
        ({"meter_id": "not-a-uuid"}, ["body", "meter_id"], "invalid_uuid"),
        ({"meter_id": 7}, ["body", "meter_id"], "invalid_type"),
        ({"readings": "x"}, ["body", "readings"], "invalid_type"),
        ({"window": None}, ["body", "window"], "invalid_type"),
    ],
)
def test_top_level_type_errors(
    client: TestClient,
    summary_body: Body,
    update: dict[str, Any],
    loc: list[object],
    code: str,
) -> None:
    body = {**summary_body([]), **update}

    assert [(e["loc"], e["code"]) for e in _errors(client, body)] == [(loc, code)]


def test_missing_required_fields(client: TestClient) -> None:
    errors = _errors(client, {})

    assert sorted(tuple(e["loc"]) for e in errors) == [
        ("body", "meter_id"),
        ("body", "readings"),
        ("body", "window"),
    ]
    assert {e["code"] for e in errors} == {"missing"}


def test_bad_enums(
    client: TestClient, summary_body: Body, reading: ReadingFactory
) -> None:
    body = _one_reading(summary_body, reading, status="deleted", source="ocr")

    assert sorted((tuple(e["loc"]), e["code"]) for e in _errors(client, body)) == [
        (("body", "readings", 0, "source"), "invalid_enum"),
        (("body", "readings", 0, "status"), "invalid_enum"),
    ]


def test_errors_are_capped_and_never_echo_input(
    client: TestClient, summary_body: Body, reading: ReadingFactory
) -> None:
    secret = "SECRET-VALUE-123"
    body = summary_body([reading("2026-10-01T16:00:00Z", secret)] * 5_000)

    response = client.post(PATH, json=body)

    problem = response.json()
    assert response.status_code == 422
    assert len(problem["errors"]) == 100
    assert problem["errors_truncated"] is True
    assert secret not in response.text
    assert problem["errors"][99]["loc"] == ["body", "readings", 99, "cumulative_kwh"]


def test_uncut_errors_are_not_truncated(
    client: TestClient, summary_body: Body, reading: ReadingFactory
) -> None:
    body = _one_reading(summary_body, reading, cumulative_kwh="x")

    assert client.post(PATH, json=body).json()["errors_truncated"] is False


def test_body_that_is_not_an_object(client: TestClient) -> None:
    assert [(e["loc"], e["code"]) for e in _errors(client, [])] == [
        (["body"], "invalid_type")
    ]
