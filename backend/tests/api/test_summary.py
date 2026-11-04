"""Summary endpoint behavior: AC-2 to AC-7 of spec 0008."""

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from energyiq.platform.clock import get_now
from energyiq.platform.http.formats import format_decimal, format_duration, format_utc
from energyiq.readings import (
    MeterEvent,
    MeterEventType,
    Reading,
    ReadingSource,
    ReadingStatus,
    compute_intervals,
    normalize_intervals,
    order_readings,
    summarize_consumption,
)
from energyiq.readings.api.mapping import to_domain
from energyiq.readings.api.schemas import ConsumptionSummaryRequest

PATH = "/api/v1/consumption/summary"
Body = Callable[..., dict[str, Any]]
ReadingFactory = Callable[..., dict[str, Any]]


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text).astimezone(UTC)


def test_happy_path_equals_direct_domain_call(
    client: TestClient, meter_id: UUID
) -> None:
    created_at = datetime(2026, 10, 30, tzinfo=UTC)
    ids = [uuid4() for _ in range(6)]
    event_id, approver = uuid4(), uuid4()
    raw = [
        (ids[0], "2026-10-01T12:00:00-04:00", "13000", "valid"),
        (ids[1], "2026-10-02T16:00:00Z", "13012.25", "valid"),
        (ids[2], "2026-10-03T16:00:00Z", "13030", "flagged"),
        (ids[3], "2026-10-04T16:00:00Z", "5", "valid"),
        (ids[4], "2026-10-05T16:00:00Z", "17.5", "valid"),
        (ids[5], "2026-10-06T16:00:00Z", "30", "valid"),
    ]
    body = {
        "meter_id": str(meter_id),
        "window": {"start": "2026-10-02T00:00:00Z", "end": "2026-10-06T04:00:00Z"},
        "readings": [
            {"id": str(i), "recorded_at": at, "cumulative_kwh": kwh, "status": status}
            for i, at, kwh, status in raw
        ],
        "events": [
            {
                "id": str(event_id),
                "event_type": "reset",
                "effective_at": "2026-10-04T10:00:00Z",
                "approved_by": str(approver),
                "approved_at": "2026-10-04T11:00:00Z",
            }
        ],
    }

    response = client.post(PATH, json=body)

    readings = [
        Reading(
            id=i,
            meter_id=meter_id,
            recorded_at=_utc(at),
            cumulative_kwh=Decimal(kwh),
            source=ReadingSource.MANUAL,
            status=ReadingStatus(status),
            created_at=created_at,
        )
        for i, at, kwh, status in raw
    ]
    events = [
        MeterEvent(
            id=event_id,
            meter_id=meter_id,
            event_type=MeterEventType.RESET,
            effective_at=_utc("2026-10-04T10:00:00Z"),
            created_at=created_at,
            approved_by=approver,
            approved_at=_utc("2026-10-04T11:00:00Z"),
        )
    ]
    intervals = compute_intervals(order_readings(readings), events)
    summary = summarize_consumption(
        intervals,
        meter_id,
        _utc("2026-10-02T00:00:00Z"),
        _utc("2026-10-06T04:00:00Z"),
    )
    normalized = normalize_intervals(intervals)

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    data = response.json()
    assert data["meter_id"] == str(meter_id)
    assert data["window"] == {
        "start": "2026-10-02T00:00:00Z",
        "end": "2026-10-06T04:00:00Z",
    }
    assert data["measured_kwh"] == format_decimal(summary.measured_kwh)
    assert data["covered"] == format_duration(summary.covered)
    assert data["uncovered"] == format_duration(summary.uncovered)
    assert data["coverage_ratio"] == format_decimal(summary.coverage_ratio)
    assert summary.average_kwh_per_day is not None
    assert data["average_kwh_per_day"] == format_decimal(summary.average_kwh_per_day)
    assert [
        (g["start"], g["end"], g["duration"], g["reason"], g["interval_reason"])
        for g in data["gaps"]
    ] == [
        (
            format_utc(g.start),
            format_utc(g.end),
            format_duration(g.duration),
            g.reason.value,
            g.interval_reason.value if g.interval_reason else None,
        )
        for g in summary.gaps
    ]
    assert [
        (
            i["previous_reading_id"],
            i["current_reading_id"],
            i["status"],
            i["reason"],
            i["event_ids"],
            i["consumption_kwh"],
            i["kwh_per_day"],
        )
        for i in data["intervals"]
    ] == [
        (
            str(n.interval.previous_reading_id),
            str(n.interval.current_reading_id),
            n.interval.status.value,
            n.interval.reason.value if n.interval.reason else None,
            [str(e) for e in n.interval.event_ids],
            None
            if n.interval.consumption_kwh is None
            else format_decimal(n.interval.consumption_kwh),
            None if n.kwh_per_day is None else format_decimal(n.kwh_per_day),
        )
        for n in normalized
    ]
    measured_ids = {
        str(item.interval.current_reading_id) for item in summary.measured_intervals
    }
    assert [i["measured_in_window"] for i in data["intervals"]] == [
        i["current_reading_id"] in measured_ids for i in data["intervals"]
    ]
    # The chain holds one of each case: crossing the window start, measured,
    # flagged, reset boundary, and crossing the window end.
    assert [i["measured_in_window"] for i in data["intervals"]] == [
        False,
        False,
        False,
        True,
        False,
    ]
    assert [i["reason"] for i in data["intervals"]] == [
        None,
        "flagged_reading",
        "meter_boundary",
        None,
        None,
    ]
    assert data["measured_kwh"] == "12.5"


def test_measured_interval_is_marked_and_summed(
    client: TestClient, summary_body: Body, reading: ReadingFactory
) -> None:
    body = summary_body(
        [
            reading("2026-10-01T16:00:00Z", "100"),
            reading("2026-10-02T16:00:00Z", "112.5"),
        ]
    )

    data = client.post(PATH, json=body).json()

    assert data["measured_kwh"] == "12.5"
    assert data["covered"] == "P1D"
    assert data["uncovered"] == "P2D"
    assert data["coverage_ratio"] == "0.3333"
    assert data["average_kwh_per_day"] == "12.500000"
    assert data["intervals"][0]["measured_in_window"] is True
    assert data["intervals"][0]["duration"] == "P1D"
    assert data["intervals"][0]["kwh_per_day"] == "12.500000"
    assert [g["reason"] for g in data["gaps"]] == [
        "before_first_reading",
        "after_last_reading",
    ]


def test_offset_input_becomes_utc_output(
    client: TestClient, summary_body: Body, reading: ReadingFactory
) -> None:
    body = summary_body(
        [
            reading("2026-10-01T12:00:00-04:00", "100"),
            reading("2026-10-02T12:00:00.000001-04:00", "101"),
        ],
        start="2026-09-30T20:00:00-04:00",
    )

    data = client.post(PATH, json=body).json()

    assert data["window"]["start"] == "2026-10-01T00:00:00Z"
    assert data["intervals"][0]["start"] == "2026-10-01T16:00:00Z"
    assert data["intervals"][0]["end"] == "2026-10-02T16:00:00.000001Z"
    assert data["intervals"][0]["duration"] == "P1DT0.000001S"


def test_nullable_fields_are_present_and_enums_are_domain_strings(
    client: TestClient, summary_body: Body, reading: ReadingFactory
) -> None:
    body = summary_body(
        [
            reading("2026-10-01T16:00:00Z", "100", status="flagged"),
            reading("2026-10-02T16:00:00Z", "101"),
        ]
    )

    data = client.post(PATH, json=body).json()

    interval = data["intervals"][0]
    assert interval["status"] == "invalid"
    assert interval["reason"] == "flagged_reading"
    assert interval["consumption_kwh"] is None
    assert interval["kwh_per_day"] is None
    assert data["average_kwh_per_day"] is None
    assert data["gaps"][0]["interval_reason"] is None
    assert data["gaps"][0]["previous_reading_id"] is None


@pytest.mark.parametrize(
    "readings",
    [
        [],
        [("2026-10-02T00:00:00Z", "1", None)],
        [
            ("2026-10-01T16:00:00Z", "1", "voided"),
            ("2026-10-02T16:00:00Z", "2", "voided"),
        ],
    ],
    ids=["empty", "single", "only_voided"],
)
def test_no_computable_interval_returns_full_no_intervals_gap(
    client: TestClient,
    summary_body: Body,
    reading: ReadingFactory,
    readings: list[tuple[str, str, str | None]],
) -> None:
    body = summary_body([reading(at, kwh, status) for at, kwh, status in readings])

    response = client.post(PATH, json=body)

    assert response.status_code == 200
    data = response.json()
    assert data["measured_kwh"] == "0"
    assert data["coverage_ratio"] == "0.0000"
    assert data["average_kwh_per_day"] is None
    assert data["covered"] == "PT0S"
    assert data["intervals"] == []
    assert data["gaps"] == [
        {
            "start": "2026-10-01T00:00:00Z",
            "end": "2026-10-04T00:00:00Z",
            "duration": "P3D",
            "reason": "no_intervals",
            "interval_reason": None,
            "previous_reading_id": None,
            "current_reading_id": None,
            "event_ids": [],
        }
    ]


def test_exponent_decimal_result_prints_fixed_point(
    client: TestClient, summary_body: Body, reading: ReadingFactory
) -> None:
    body = summary_body(
        [
            reading("2026-10-01T16:00:00Z", "5.000000"),
            reading("2026-10-02T16:00:00Z", "5.00"),
        ]
    )

    data = client.post(PATH, json=body).json()

    assert data["intervals"][0]["consumption_kwh"] == format_decimal(
        Decimal("5.00") - Decimal("5.000000")
    )
    assert "E" not in data["intervals"][0]["consumption_kwh"]
    assert "E" not in data["measured_kwh"]


def test_kwh_string_with_trailing_zero_succeeds(
    client: TestClient, summary_body: Body, reading: ReadingFactory
) -> None:
    body = summary_body(
        [
            reading("2026-10-01T16:00:00Z", "13049.0"),
            reading("2026-10-02T16:00:00Z", "13050.000000"),
        ]
    )

    response = client.post(PATH, json=body)

    assert response.status_code == 200
    assert response.json()["measured_kwh"] == "1.000000"


def test_status_and_source_defaults_and_server_created_at(meter_id: UUID) -> None:
    frozen = datetime(2026, 11, 1, 12, tzinfo=UTC)
    request = ConsumptionSummaryRequest.model_validate(
        {
            "meter_id": str(meter_id),
            "window": {"start": "2026-10-01T00:00:00Z", "end": "2026-10-02T00:00:00Z"},
            "readings": [
                {
                    "id": str(uuid4()),
                    "recorded_at": "2026-10-01T16:00:00Z",
                    "cumulative_kwh": "1",
                }
            ],
            "events": [
                {
                    "id": str(uuid4()),
                    "event_type": "installed",
                    "effective_at": "2026-10-01T10:00:00Z",
                }
            ],
        }
    )

    readings, events = to_domain(request, frozen)

    assert readings[0].status is ReadingStatus.VALID
    assert readings[0].source is ReadingSource.MANUAL
    assert readings[0].created_at == frozen
    assert readings[0].meter_id == meter_id
    assert events[0].created_at == frozen
    assert events[0].meter_id == meter_id


def test_route_stamps_one_instant_from_the_injected_clock(
    app: FastAPI, summary_body: Body, reading: ReadingFactory
) -> None:
    calls: list[datetime] = []

    def frozen_now() -> datetime:
        calls.append(datetime(2026, 11, 1, tzinfo=UTC))
        return calls[-1]

    app.dependency_overrides[get_now] = frozen_now
    body = summary_body(
        [reading("2026-10-01T16:00:00Z", "1"), reading("2026-10-02T16:00:00Z", "2")]
    )

    response = TestClient(app).post(PATH, json=body, headers={"X-EnergyIQ-CSRF": "1"})

    assert response.status_code == 200
    assert len(calls) == 1


def test_duplicate_ids_return_every_index(
    client: TestClient, summary_body: Body, reading: ReadingFactory
) -> None:
    shared = uuid4()
    event_id = uuid4()
    readings = [
        reading("2026-10-01T16:00:00Z", "1", reading_id=shared),
        reading("2026-10-02T16:00:00Z", "2"),
        reading("2026-10-03T16:00:00Z", "3", reading_id=shared),
        reading("2026-10-03T17:00:00Z", "4", reading_id=shared),
    ]
    event = {
        "id": str(event_id),
        "event_type": "reset",
        "effective_at": "2026-10-02T00:00:00Z",
    }
    body = summary_body(readings, events=[event, event])

    response = client.post(PATH, json=body)

    assert response.status_code == 422
    problem = response.json()
    assert problem["code"] == "duplicate_id"
    assert problem["duplicates"] == [
        {"collection": "readings", "id": str(shared), "input_indexes": [0, 2, 3]},
        {"collection": "events", "id": str(event_id), "input_indexes": [0, 1]},
    ]


def test_reading_and_event_may_share_an_id(
    client: TestClient, summary_body: Body, reading: ReadingFactory
) -> None:
    shared = uuid4()
    body = summary_body(
        [reading("2026-10-01T16:00:00Z", "1", reading_id=shared)],
        events=[
            {
                "id": str(shared),
                "event_type": "reset",
                "effective_at": "2026-10-02T00:00:00Z",
            }
        ],
    )

    assert client.post(PATH, json=body).status_code == 200


def test_timestamp_conflicts_include_voided_readings(
    client: TestClient, summary_body: Body, reading: ReadingFactory
) -> None:
    first, second, third = uuid4(), uuid4(), uuid4()
    body = summary_body(
        [
            reading("2026-10-01T16:00:00Z", "1", reading_id=first),
            reading("2026-10-02T16:00:00Z", "2"),
            reading("2026-10-01T12:00:00-04:00", "1", "voided", reading_id=second),
            reading("2026-10-03T16:00:00Z", "3", reading_id=third),
            reading("2026-10-03T16:00:00Z", "3", "flagged"),
        ]
    )

    response = client.post(PATH, json=body)

    assert response.status_code == 422
    problem = response.json()
    assert problem["code"] == "reading_timestamp_conflict"
    conflicts = problem["conflicts"]
    assert [c["recorded_at"] for c in conflicts] == [
        "2026-10-01T16:00:00Z",
        "2026-10-03T16:00:00Z",
    ]
    assert conflicts[0]["entries"] == [
        {"input_index": 0, "reading_id": str(first), "status": "valid"},
        {"input_index": 2, "reading_id": str(second), "status": "voided"},
    ]
    assert [e["input_index"] for e in conflicts[1]["entries"]] == [3, 4]
    assert [e["status"] for e in conflicts[1]["entries"]] == ["valid", "flagged"]


def test_duplicate_ids_answer_before_conflicts(
    client: TestClient, summary_body: Body, reading: ReadingFactory
) -> None:
    shared = uuid4()
    body = summary_body(
        [
            reading("2026-10-01T16:00:00Z", "1", reading_id=shared),
            reading("2026-10-01T16:00:00Z", "1", reading_id=shared),
        ]
    )

    assert client.post(PATH, json=body).json()["code"] == "duplicate_id"


def test_schema_errors_answer_before_duplicates(
    client: TestClient, summary_body: Body, reading: ReadingFactory
) -> None:
    shared = uuid4()
    body = summary_body(
        [
            reading("2026-10-01T16:00:00Z", "1", reading_id=shared),
            reading("2026-10-01T16:00:00Z", "-1", reading_id=shared),
        ]
    )

    assert client.post(PATH, json=body).json()["code"] == "validation_error"


def test_summary_needs_no_credentials(client: TestClient, summary_body: Body) -> None:
    response = client.post(
        PATH, json=summary_body([]), headers={"Origin": "http://localhost:3000"}
    )

    assert response.status_code == 200
    assert "access-control-allow-credentials" not in response.headers
