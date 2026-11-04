"""Stored summaries agree with the full history domain oracle."""

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from hypothesis import HealthCheck, example, given, settings
from hypothesis import strategies as st

from energyiq.readings import (
    compute_intervals,
    normalize_intervals,
    order_readings,
    summarize_consumption,
)
from energyiq.readings.api.mapping import to_response
from energyiq.readings.models import (
    MeterEvent,
    MeterEventType,
    Reading,
    ReadingSource,
    ReadingStatus,
)

pytestmark = pytest.mark.db


def _instant(value: str) -> datetime:
    return datetime.fromisoformat(value)


# Readings sit at noon on 2026-11-01..04. Window starts run from three days
# before the first reading to four days after the last, so a window can lie
# wholly before the history, straddle either edge, or lie wholly after it.
WINDOW_BASE = _instant("2026-10-29T00:00:00Z")


@settings(
    max_examples=12,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(
    values=st.lists(st.integers(min_value=0, max_value=500), min_size=4, max_size=4),
    start_day=st.integers(min_value=0, max_value=10),
    span=st.integers(min_value=1, max_value=3),
    approve=st.booleans(),
)
# Wholly before the history: 2026-10-29 to 2026-11-01, ending before noon.
@example(values=[10, 20, 30, 40], start_day=0, span=3, approve=False)
# Wholly after it: 2026-11-06 to 2026-11-09.
@example(values=[10, 20, 30, 40], start_day=8, span=3, approve=True)
def test_stored_summary_matches_full_history(
    api: TestClient,
    owner: dict[str, Any],
    values: list[int],
    start_day: int,
    span: int,
    approve: bool,
) -> None:
    home = api.post("/api/v1/properties", json={"nickname": uuid4().hex}).json()
    created = api.post(
        f"/api/v1/properties/{home['id']}/meters",
        json={"distributor": "EDESUR", "label": "Main"},
    )
    assert created.status_code == 201, created.text
    meter_id = UUID(created.json()["id"])
    path = f"/api/v1/meters/{meter_id}"
    stored: list[dict[str, Any]] = []
    for day, value in enumerate(values, start=1):
        response = api.post(
            f"{path}/readings",
            json={
                "recorded_at": f"2026-11-0{day}T12:00:00Z",
                "cumulative_kwh": str(value),
            },
        )
        assert response.status_code == 201, response.text
        stored.append(response.json())
    second = stored[1]
    assert (
        api.patch(
            f"{path}/readings/{second['id']}", json={"status": "voided"}
        ).status_code
        == 200
    )
    replacement = api.post(
        f"{path}/readings",
        json={
            "recorded_at": second["recorded_at"],
            "cumulative_kwh": str(values[1] + 1),
        },
    )
    assert replacement.status_code == 201, replacement.text
    stored[1] = replacement.json()
    event = api.post(
        f"{path}/events",
        json={"event_type": "reset", "effective_at": "2026-11-02T12:00:00Z"},
    )
    assert event.status_code == 201, event.text
    event_body = event.json()
    if approve:
        event_body = api.post(f"{path}/events/{event_body['id']}/approve").json()
    start = WINDOW_BASE + timedelta(days=start_day)
    end = start + timedelta(days=span)
    response = api.get(
        f"{path}/consumption", params={"from": start.isoformat(), "to": end.isoformat()}
    )
    assert response.status_code == 200, response.text
    readings = [
        Reading(
            id=UUID(row["id"]),
            meter_id=meter_id,
            recorded_at=_instant(row["recorded_at"]),
            cumulative_kwh=Decimal(row["cumulative_kwh"]),
            source=ReadingSource(row["source"]),
            status=ReadingStatus(row["status"]),
            created_at=_instant(row["created_at"]),
        )
        for row in stored
    ]
    events = [
        MeterEvent(
            id=UUID(event_body["id"]),
            meter_id=meter_id,
            event_type=MeterEventType.RESET,
            effective_at=_instant(event_body["effective_at"]),
            created_at=_instant(event_body["created_at"]),
            approved_by=UUID(event_body["decided_by"]) if approve else None,
            approved_at=_instant(event_body["decided_at"]) if approve else None,
        )
    ]
    chain = compute_intervals(order_readings(readings), events)
    summary = summarize_consumption(chain, meter_id, start, end)
    overlap = [
        item
        for item in normalize_intervals(chain)
        if item.interval.start < end and item.interval.end > start
    ]
    expected = to_response(summary, overlap).model_dump(mode="json")
    assert response.json() == expected
