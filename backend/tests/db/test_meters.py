"""Meters: create, list, patch, deactivate (spec 0009/0002 AC-8 to AC-10). Synthetic."""

from collections.abc import Callable
from typing import Any
from uuid import uuid4

import pytest
from dbsupport import Clock, Probe, without_request_id
from fastapi.testclient import TestClient

pytestmark = pytest.mark.db

Register = Callable[..., dict[str, Any]]


@pytest.fixture
def home(api: TestClient, owner: dict[str, Any]) -> str:
    """The meters path of a property the signed in owner holds."""
    created = api.post("/api/v1/properties", json={"nickname": "Casa"}).json()
    return f"/api/v1/properties/{created['id']}/meters"


def _meter(client: TestClient, path: str, **body: Any) -> Any:
    return client.post(path, json={"distributor": "EDESUR", "label": "Main", **body})


def test_create_returns_an_active_meter(
    api: TestClient, home: str, probe: Probe
) -> None:
    response = _meter(api, home, label=" Main ", register_digits=6)

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {
        "id", "property_id", "distributor", "label", "register_digits",
        "active", "deactivated_at", "created_at", "updated_at",
    }  # fmt: skip
    assert body["label"] == "Main"
    assert body["register_digits"] == 6
    assert body["active"] is True
    assert body["deactivated_at"] is None
    assert home.endswith(f"{body['property_id']}/meters")
    assert probe.audit(body["id"])[0]["metadata"] == {
        "fields": ["distributor", "label", "register_digits"]
    }


@pytest.mark.parametrize(
    ("body", "loc", "code"),
    [
        ({"register_digits": 3}, "register_digits", "invalid_register_digits"),
        ({"register_digits": 10}, "register_digits", "invalid_register_digits"),
        ({"register_digits": "6"}, "register_digits", "invalid_register_digits"),
        ({"register_digits": 6.0}, "register_digits", "invalid_register_digits"),
        ({"register_digits": True}, "register_digits", "invalid_register_digits"),
        ({"distributor": "EDEMARS"}, "distributor", "invalid_enum"),
        ({"label": ""}, "label", "invalid_text_length"),
        ({"label": "l" * 61}, "label", "invalid_text_length"),
        ({"active": False}, None, "unknown_field"),
    ],
)
def test_create_validation(
    api: TestClient, home: str, body: dict[str, Any], loc: str | None, code: str
) -> None:
    response = _meter(api, home, **body)

    assert response.status_code == 422
    error = response.json()["errors"][0]
    assert (error["loc"], error["code"]) == (["body", loc] if loc else ["body"], code)


@pytest.mark.parametrize("digits", [4, 9, None])
def test_register_digit_bounds(api: TestClient, home: str, digits: int | None) -> None:
    assert _meter(api, home, register_digits=digits).json()["register_digits"] == digits


def test_label_is_unique_among_active_meters(api: TestClient, home: str) -> None:
    first = _meter(api, home).json()

    duplicate = _meter(api, home, label="MAIN")
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "meter_label_taken"

    deactivated = api.post(f"/api/v1/meters/{first['id']}/deactivate")
    assert deactivated.status_code == 200
    replacement = _meter(api, home, label="main")
    assert replacement.status_code == 201
    assert replacement.json()["id"] != first["id"]


def test_deactivate_is_terminal(
    api: TestClient, home: str, clock: Clock, probe: Probe
) -> None:
    meter = _meter(api, home).json()
    path = f"/api/v1/meters/{meter['id']}"
    clock.advance(hours=23)  # a full day would also end the idle session

    response = api.post(f"{path}/deactivate")

    assert response.status_code == 200
    body = response.json()
    assert body["active"] is False
    assert body["deactivated_at"] == body["updated_at"] == "2026-11-05T11:00:00Z"
    for again in (
        api.post(f"{path}/deactivate"),
        api.patch(path, json={"label": "Old"}),
    ):
        assert again.status_code == 409
        assert again.json()["code"] == "meter_inactive"
    assert api.get(path).json()["active"] is False
    assert [(a["action"], a["metadata"]) for a in probe.audit(meter["id"])] == [
        ("meter.create", {"fields": ["distributor", "label"]}),
        ("meter.deactivate", {"fields": ["active", "deactivated_at"]}),
    ]


def test_list_hides_inactive_meters_unless_asked(
    api: TestClient, home: str, clock: Clock
) -> None:
    old = _meter(api, home).json()
    clock.advance(seconds=1)
    api.post(f"/api/v1/meters/{old['id']}/deactivate")
    new = _meter(api, home).json()

    default = api.get(home).json()
    everything = api.get(home, params={"include_inactive": "true"}).json()

    assert [m["id"] for m in default["items"]] == [new["id"]]
    assert [m["id"] for m in everything["items"]] == [old["id"], new["id"]]
    assert everything["next_cursor"] is None


def test_list_pages(api: TestClient, home: str, clock: Clock) -> None:
    ids: list[str] = []
    for label in ("A", "B", "C"):
        ids.append(_meter(api, home, label=label).json()["id"])
        clock.advance(seconds=1)

    first = api.get(home, params={"limit": 2}).json()
    rest = api.get(home, params={"cursor": first["next_cursor"]}).json()

    assert [m["id"] for m in first["items"] + rest["items"]] == ids
    assert rest["next_cursor"] is None


def test_patch_label_and_digits(
    api: TestClient, home: str, clock: Clock, probe: Probe
) -> None:
    meter = _meter(api, home, register_digits=5).json()
    path = f"/api/v1/meters/{meter['id']}"
    clock.advance(minutes=1)

    renamed = api.patch(path, json={"label": "Kitchen"})
    cleared = api.patch(path, json={"register_digits": None})

    assert renamed.status_code == 200
    assert renamed.json()["label"] == "Kitchen"
    assert renamed.json()["register_digits"] == 5
    assert renamed.json()["updated_at"] == "2026-11-04T12:01:00Z"
    assert cleared.json()["register_digits"] is None
    assert cleared.json()["label"] == "Kitchen"
    updates = [
        a["metadata"] for a in probe.audit(meter["id"]) if a["action"] == "meter.update"
    ]
    assert updates == [{"fields": ["label"]}, {"fields": ["register_digits"]}]


@pytest.mark.parametrize(
    ("body", "loc", "code"),
    [
        ({}, ["body"], "empty_patch"),
        ({"label": None}, ["body", "label"], "invalid_type"),
        ({"distributor": "EDEESTE"}, ["body"], "unknown_field"),
    ],
)
def test_patch_validation(
    api: TestClient, home: str, body: dict[str, Any], loc: list[str], code: str
) -> None:
    meter = _meter(api, home).json()

    response = api.patch(f"/api/v1/meters/{meter['id']}", json=body)

    assert response.status_code == 422
    error = response.json()["errors"][0]
    assert (error["loc"], error["code"]) == (loc, code)


def test_patch_to_a_taken_label_is_409(api: TestClient, home: str) -> None:
    _meter(api, home, label="Main")
    other = _meter(api, home, label="Garage").json()

    response = api.patch(f"/api/v1/meters/{other['id']}", json={"label": "main"})

    assert response.status_code == 409
    assert response.json()["code"] == "meter_label_taken"


def test_other_owners_meter_is_indistinguishable_from_a_missing_one(
    api: TestClient,
    home: str,
    new_client: Callable[[], TestClient],
    register: Register,
) -> None:
    meter = _meter(api, home).json()
    stranger = new_client()
    register(stranger, "stranger@example.test")

    requests: list[tuple[str, str, dict[str, Any] | None]] = [
        ("GET", "/api/v1/meters/{}", None),
        ("PATCH", "/api/v1/meters/{}", {"label": "Mine now"}),
        ("POST", "/api/v1/meters/{}/deactivate", None),
    ]
    for method, template, body in requests:
        theirs = stranger.request(method, template.format(meter["id"]), json=body)
        nowhere = stranger.request(method, template.format(uuid4()), json=body)
        assert theirs.status_code == nowhere.status_code == 404
        assert without_request_id(theirs.json()) == without_request_id(nowhere.json())

    their_home = stranger.get(home)
    assert their_home.status_code == 404
    assert _meter(stranger, home).status_code == 404
    assert api.get(f"/api/v1/meters/{meter['id']}").json()["active"] is True
