"""Stored readings and events through the authenticated API, with synthetic data."""

import logging
from typing import Any
from uuid import uuid4

import pytest
from dbsupport import Probe
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from energyiq.readings.api import stored_router

pytestmark = pytest.mark.db


@pytest.fixture
def meter(api: TestClient, owner: dict[str, Any]) -> str:
    home = api.post("/api/v1/properties", json={"nickname": "Casa"})
    assert home.status_code == 201, home.text
    created = api.post(
        f"/api/v1/properties/{home.json()['id']}/meters",
        json={"distributor": "EDESUR", "label": "Main"},
    )
    assert created.status_code == 201, created.text
    return f"/api/v1/meters/{created.json()['id']}"


def test_reading_date_collision_status_and_replacement(
    api: TestClient, meter: str, probe: Probe
) -> None:
    path = f"{meter}/readings"
    created = api.post(
        path, json={"local_date": "2026-11-03", "cumulative_kwh": "13049"}
    )
    assert created.status_code == 201, created.text
    first = created.json()
    assert first["recorded_at"] == "2026-11-03T16:00:00Z"
    assert first["cumulative_kwh"] == "13049.000000"
    duplicate = api.post(
        path, json={"recorded_at": first["recorded_at"], "cumulative_kwh": "13050"}
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["existing_reading_id"] == first["id"]
    listed = api.get(path).json()
    assert [row["id"] for row in listed["items"]] == [first["id"]]
    flagged = api.patch(f"{path}/{first['id']}", json={"status": "flagged"})
    assert flagged.status_code == 200, flagged.text
    voided = api.patch(f"{path}/{first['id']}", json={"status": "voided"})
    assert voided.status_code == 200, voided.text
    assert (
        api.patch(f"{path}/{first['id']}", json={"status": "valid"}).json()["code"]
        == "reading_voided"
    )
    assert (
        api.patch(f"{path}/{first['id']}", json={"status": "voided"}).status_code == 200
    )
    replacement = api.post(
        path, json={"recorded_at": first["recorded_at"], "cumulative_kwh": "13050"}
    )
    assert replacement.status_code == 201, replacement.text
    assert [row["action"] for row in probe.audit(first["id"])] == [
        "reading.create",
        "reading.status_change",
        "reading.status_change",
    ]


def test_events_and_stored_consumption(api: TestClient, meter: str) -> None:
    path = f"{meter}/readings"
    for instant, value in [
        ("2026-11-01T12:00:00Z", "100"),
        ("2026-11-03T12:00:00Z", "20"),
    ]:
        response = api.post(
            path, json={"recorded_at": instant, "cumulative_kwh": value}
        )
        assert response.status_code == 201, response.text
    window = "from=2026-11-01T00%3A00%3A00Z&to=2026-11-04T00%3A00%3A00Z"
    before = api.get(f"{meter}/consumption?{window}")
    assert before.status_code == 200, before.text
    assert before.json()["intervals"][0]["reason"] == "unexplained_decrease"
    event = api.post(
        f"{meter}/events",
        json={
            "event_type": "reset",
            "effective_at": "2026-11-02T12:00:00Z",
            "note": "   ",
        },
    )
    assert event.status_code == 201, event.text
    assert event.json()["note"] is None
    assert api.post(f"{meter}/deactivate").status_code == 200
    decided = api.post(f"{meter}/events/{event.json()['id']}/approve")
    assert decided.status_code == 200, decided.text
    assert (
        api.post(f"{meter}/events/{event.json()['id']}/reject").json()["code"]
        == "event_not_pending"
    )
    assert api.get(f"{meter}/consumption?{window}").status_code == 200


def test_consumption_boundary_gaps_distinguish_history_from_no_intervals(
    api: TestClient, meter: str
) -> None:
    def gap(start: str, end: str) -> str:
        response = api.get(f"{meter}/consumption", params={"from": start, "to": end})
        assert response.status_code == 200, response.text
        assert response.json()["intervals"] == []
        return response.json()["gaps"][0]["reason"]

    assert gap("2026-11-01T00:00:00Z", "2026-11-02T00:00:00Z") == "no_intervals"
    first = api.post(
        f"{meter}/readings",
        json={"recorded_at": "2026-11-02T12:00:00Z", "cumulative_kwh": "10"},
    )
    assert first.status_code == 201, first.text
    assert gap("2026-11-01T00:00:00Z", "2026-11-02T00:00:00Z") == "no_intervals"
    second = api.post(
        f"{meter}/readings",
        json={"recorded_at": "2026-11-03T12:00:00Z", "cumulative_kwh": "20"},
    )
    assert second.status_code == 201, second.text
    assert gap("2026-11-01T00:00:00Z", "2026-11-02T00:00:00Z") == "before_first_reading"
    assert gap("2026-11-04T00:00:00Z", "2026-11-05T00:00:00Z") == "after_last_reading"
    assert gap("2026-11-01T00:00:00Z", "2026-11-02T12:00:00Z") == "before_first_reading"
    assert gap("2026-11-03T12:00:00Z", "2026-11-04T00:00:00Z") == "after_last_reading"


def test_retry_replays_after_deactivation(
    api: TestClient, meter: str, probe: Probe
) -> None:
    path = f"{meter}/readings"
    body = {"recorded_at": "2026-11-03T12:00:00Z", "cumulative_kwh": "15"}
    headers = {"Idempotency-Key": "retry-one"}
    first = api.post(path, json=body, headers=headers)
    assert first.status_code == 201, first.text
    assert api.post(f"{meter}/deactivate").status_code == 200
    replay = api.post(path, json=body, headers=headers)
    assert replay.status_code == 201, replay.text
    assert replay.content == first.content
    assert replay.headers["Idempotent-Replayed"] == "true"
    assert len(probe.audit(first.json()["id"])) == 1
    changed = api.post(path, json={**body, "cumulative_kwh": "16"}, headers=headers)
    assert changed.status_code == 409
    assert changed.json()["code"] == "idempotency_key_reused"


def test_existing_property_and_meter_posts_replay(
    api: TestClient, owner: dict[str, Any], probe: Probe
) -> None:
    headers = {"Idempotency-Key": "home-retry"}
    body = {"nickname": "Retry home"}
    first = api.post("/api/v1/properties", json=body, headers=headers)
    replay = api.post("/api/v1/properties", json=body, headers=headers)
    assert first.status_code == replay.status_code == 201
    assert first.content == replay.content
    assert replay.headers["Idempotent-Replayed"] == "true"
    assert len(probe.audit(first.json()["id"])) == 1
    path = f"/api/v1/properties/{first.json()['id']}/meters"
    meter_body = {"distributor": "EDESUR", "label": "Main"}
    meter_headers = {"Idempotency-Key": "meter-retry"}
    created = api.post(path, json=meter_body, headers=meter_headers)
    again = api.post(path, json=meter_body, headers=meter_headers)
    assert created.status_code == again.status_code == 201
    assert created.content == again.content
    assert len(probe.audit(created.json()["id"])) == 1


def test_future_range_pagination_and_inactive_rules(
    api: TestClient, meter: str
) -> None:
    path = f"{meter}/readings"
    assert (
        api.post(path, json={"local_date": "2026-11-05", "cumulative_kwh": "1"}).json()[
            "errors"
        ][0]["code"]
        == "reading_in_future"
    )
    assert (
        api.post(
            path, json={"recorded_at": "2026-11-04T12:06:00Z", "cumulative_kwh": "1"}
        ).json()["errors"][0]["code"]
        == "reading_in_future"
    )
    assert (
        api.post(path, json={"cumulative_kwh": "1"}).json()["errors"][0]["code"]
        == "exactly_one_of"
    )
    for day in (1, 2, 3):
        response = api.post(
            path,
            json={
                "recorded_at": f"2026-11-0{day}T12:00:00Z",
                "cumulative_kwh": str(day),
            },
        )
        assert response.status_code == 201, response.text
    first = api.get(f"{path}?limit=2")
    assert first.status_code == 200, first.text
    assert len(first.json()["items"]) == 2
    second = api.get(path, params={"limit": 2, "cursor": first.json()["next_cursor"]})
    assert second.status_code == 200, second.text
    assert len(second.json()["items"]) == 1
    assert second.json()["next_cursor"] is None
    filtered = api.get(
        path, params={"from": "2026-11-02T00:00:00Z", "to": "2026-11-03T00:00:00Z"}
    )
    assert filtered.json()["items"][0]["cumulative_kwh"] == "2.000000"
    assert (
        api.get(
            path, params={"from": "2026-11-03T00:00:00Z", "to": "2026-11-02T00:00:00Z"}
        ).json()["errors"][0]["code"]
        == "range_order"
    )
    assert (
        api.get(
            f"{meter}/consumption",
            params={"from": "2025-01-01T00:00:00Z", "to": "2026-11-04T00:00:00Z"},
        ).json()["errors"][0]["code"]
        == "window_too_long"
    )
    assert api.post(f"{meter}/deactivate").status_code == 200
    assert (
        api.post(
            path, json={"recorded_at": "2026-11-04T12:00:00Z", "cumulative_kwh": "4"}
        ).json()["code"]
        == "meter_inactive"
    )
    assert (
        api.post(
            f"{meter}/events",
            json={"event_type": "reset", "effective_at": "2026-11-03T00:00:00Z"},
        ).json()["code"]
        == "meter_inactive"
    )


def test_cross_owner_and_wrong_meter_are_hidden(
    api: TestClient, meter: str, new_client: Any, register: Any
) -> None:
    reading = api.post(
        f"{meter}/readings",
        json={"recorded_at": "2026-11-03T12:00:00Z", "cumulative_kwh": "1"},
    ).json()
    other = new_client()
    register(other, email="other@example.test")
    assert other.get(f"{meter}/readings").status_code == 404
    assert other.get(f"{meter}/events").status_code == 404
    assert (
        other.get(
            f"{meter}/consumption",
            params={"from": "2026-11-01T00:00:00Z", "to": "2026-11-04T00:00:00Z"},
        ).status_code
        == 404
    )
    assert (
        api.patch(
            f"/api/v1/meters/{uuid4()}/readings/{reading['id']}",
            json={"status": "flagged"},
        ).status_code
        == 404
    )


def test_failed_retry_key_is_reusable_and_expired_key_is_overwritten(
    api: TestClient, meter: str, probe: Probe
) -> None:
    path = f"{meter}/readings"
    first = {"recorded_at": "2026-11-01T12:00:00Z", "cumulative_kwh": "10"}
    assert api.post(path, json=first).status_code == 201
    headers = {"Idempotency-Key": "recover"}
    failed = api.post(path, json=first, headers=headers)
    assert failed.status_code == 409
    assert probe.one("SELECT count(*) FROM idempotency_keys WHERE key = 'recover'") == 0
    changed = {"recorded_at": "2026-11-02T12:00:00Z", "cumulative_kwh": "11"}
    assert api.post(path, json=changed, headers=headers).status_code == 201
    probe.run(
        "UPDATE idempotency_keys SET expires_at = '2026-11-01T00:00:00Z' WHERE key = 'recover'"
    )
    newer = {"recorded_at": "2026-11-03T12:00:00Z", "cumulative_kwh": "12"}
    response = api.post(path, json=newer, headers=headers)
    assert response.status_code == 201, response.text
    assert response.headers.get("Idempotent-Replayed") is None


class _Diag:
    constraint_name = "uq_some_other_constraint"


class _Orig(Exception):
    diag = _Diag()


def test_unmapped_reading_integrity_error_drops_postgres_detail(
    api: TestClient,
    meter: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    detail = "DETAIL: Key (secret)=(owner@example.test) already exists."

    def violate(*_args: object, **_kwargs: object) -> object:
        raise IntegrityError("INSERT ...", {}, _Orig(detail))

    monkeypatch.setattr(stored_router, "execute_idempotent", violate)
    with caplog.at_level(logging.ERROR, logger="energyiq.errors"):
        response = api.post(
            f"{meter}/readings",
            json={"recorded_at": "2026-11-01T12:00:00Z", "cumulative_kwh": "1"},
        )
    assert response.status_code == 500
    assert "owner@example.test" not in response.text
    logged = " ".join(
        str(value) for record in caplog.records for value in vars(record).values()
    )
    assert "uq_some_other_constraint" in logged
    assert "owner@example.test" not in logged
