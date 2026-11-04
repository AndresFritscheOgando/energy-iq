"""Owner scoped properties (spec 0009/0002 AC-7, AC-9, AC-10). Synthetic data."""

import logging
from collections.abc import Callable
from typing import Any
from uuid import uuid4

import pytest
from dbsupport import Clock, Probe, without_request_id
from fastapi.testclient import TestClient

pytestmark = pytest.mark.db

Register = Callable[..., dict[str, Any]]
PROPERTIES = "/api/v1/properties"


def _create(client: TestClient, **body: Any) -> Any:
    return client.post(PROPERTIES, json={"nickname": "Casa", **body})


@pytest.fixture
def stranger(new_client: Callable[[], TestClient], register: Register) -> TestClient:
    """A second signed in owner with a separate cookie jar."""
    client = new_client()
    register(client, "stranger@example.test")
    return client


def test_create_returns_the_property_with_defaults(
    api: TestClient, owner: dict[str, Any], probe: Probe
) -> None:
    response = _create(api, nickname="  Casa  ", region="")

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {
        "id",
        "nickname",
        "region",
        "timezone",
        "created_at",
        "updated_at",
    }
    assert body["nickname"] == "Casa"
    assert body["region"] is None
    assert body["timezone"] == "America/Santo_Domingo"
    assert body["created_at"] == body["updated_at"] == "2026-11-04T12:00:00Z"
    stored = probe.rows("SELECT owner_user_id FROM properties")
    assert [str(row["owner_user_id"]) for row in stored] == [owner["id"]]
    audit = probe.audit(body["id"])
    assert [(a["action"], a["entity_type"], a["metadata"]) for a in audit] == [
        ("property.create", "property", {"fields": ["nickname", "region"]})
    ]
    assert str(audit[0]["actor_user_id"]) == owner["id"]


@pytest.mark.parametrize(
    ("body", "loc", "code"),
    [
        ({"nickname": ""}, "nickname", "invalid_text_length"),
        ({"nickname": "   "}, "nickname", "invalid_text_length"),
        ({"nickname": "x" * 81}, "nickname", "invalid_text_length"),
        ({"nickname": "Casa", "region": "r" * 81}, "region", "invalid_text_length"),
        (
            {"nickname": "Casa", "timezone": "Mars/Olympus"},
            "timezone",
            "invalid_timezone",
        ),
        (
            {"nickname": "Casa", "timezone": "america/santo_domingo"},
            "timezone",
            "invalid_timezone",
        ),
        (
            {"nickname": "Casa", "owner_user_id": str(uuid4())},
            None,
            "unknown_field",
        ),
        ({"nickname": 7}, "nickname", "invalid_type"),
    ],
)
def test_create_validation(
    api: TestClient,
    owner: dict[str, Any],
    body: dict[str, Any],
    loc: str | None,
    code: str,
) -> None:
    response = api.post(PROPERTIES, json=body)

    assert response.status_code == 422
    error = response.json()["errors"][0]
    assert (error["loc"], error["code"]) == (["body", loc] if loc else ["body"], code)


def test_eighty_character_nickname_and_region_fit(
    api: TestClient, owner: dict[str, Any]
) -> None:
    response = _create(api, nickname="n" * 80, region=" " + "r" * 80 + " ")

    assert response.status_code == 201
    assert response.json()["region"] == "r" * 80


def test_nickname_is_unique_case_insensitively_until_archived(
    api: TestClient, owner: dict[str, Any], probe: Probe
) -> None:
    first = _create(api).json()

    duplicate = _create(api, nickname=" casa ")
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "property_name_taken"
    assert "casa" not in duplicate.text.lower().replace("property", "")

    assert api.delete(f"{PROPERTIES}/{first['id']}").status_code == 204
    assert _create(api, nickname="CASA").status_code == 201
    assert probe.one("SELECT count(*) FROM properties") == 2


def test_another_owner_may_reuse_a_nickname(
    api: TestClient, owner: dict[str, Any], stranger: TestClient
) -> None:
    assert _create(api).status_code == 201
    assert _create(stranger).status_code == 201


def test_list_is_paginated_by_creation(
    api: TestClient, owner: dict[str, Any], clock: Clock, stranger: TestClient
) -> None:
    ids: list[str] = []
    for name in ("A", "B", "C"):
        ids.append(_create(api, nickname=name).json()["id"])
        clock.advance(microseconds=1)
    _create(stranger, nickname="Not mine")

    first = api.get(PROPERTIES, params={"limit": 2}).json()
    second = api.get(
        PROPERTIES, params={"limit": 2, "cursor": first["next_cursor"]}
    ).json()

    assert [item["id"] for item in first["items"]] == ids[:2]
    assert first["next_cursor"] is not None
    assert [item["id"] for item in second["items"]] == ids[2:]
    assert second["next_cursor"] is None
    assert api.get(PROPERTIES).json()["next_cursor"] is None


def test_same_instant_rows_page_by_id(api: TestClient, owner: dict[str, Any]) -> None:
    created = sorted(_create(api, nickname=name).json()["id"] for name in "ABCD")

    seen: list[str] = []
    cursor: str | None = None
    while True:
        params: dict[str, Any] = {"limit": 1}
        if cursor:
            params["cursor"] = cursor
        page = api.get(PROPERTIES, params=params).json()
        seen += [item["id"] for item in page["items"]]
        cursor = page["next_cursor"]
        if cursor is None:
            break

    assert seen == created


@pytest.mark.parametrize(
    ("params", "loc", "code"),
    [
        ({"cursor": "not a cursor!"}, ["query", "cursor"], "invalid_cursor"),
        ({"cursor": "e30"}, ["query", "cursor"], "invalid_cursor"),
        ({"limit": 0}, ["query", "limit"], "invalid_value"),
        ({"limit": 501}, ["query", "limit"], "invalid_value"),
    ],
)
def test_list_query_validation(
    api: TestClient,
    owner: dict[str, Any],
    params: dict[str, Any],
    loc: list[str],
    code: str,
) -> None:
    response = api.get(PROPERTIES, params=params)

    assert response.status_code == 422
    assert response.json()["detail"] == "The request failed validation."
    error = response.json()["errors"][0]
    assert (error["loc"], error["code"]) == (loc, code)


def test_patch_changes_named_fields_only(
    api: TestClient, owner: dict[str, Any], clock: Clock, probe: Probe
) -> None:
    created = _create(api, region="Santo Domingo Este").json()
    clock.advance(minutes=1)

    response = api.patch(
        f"{PROPERTIES}/{created['id']}",
        json={"region": None, "timezone": "America/New_York"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["nickname"] == "Casa"
    assert body["region"] is None
    assert body["timezone"] == "America/New_York"
    assert body["created_at"] == created["created_at"]
    assert body["updated_at"] == "2026-11-04T12:01:00Z"
    assert probe.audit(created["id"])[-1]["metadata"] == {
        "fields": ["region", "timezone"]
    }


@pytest.mark.parametrize(
    ("body", "loc", "code"),
    [
        ({}, ["body"], "empty_patch"),
        ({"nickname": None}, ["body", "nickname"], "invalid_type"),
        ({"timezone": None}, ["body", "timezone"], "invalid_type"),
        (
            {"archived_at": "2026-11-04T12:00:00Z"},
            ["body"],
            "unknown_field",
        ),
    ],
)
def test_patch_validation(
    api: TestClient,
    owner: dict[str, Any],
    body: dict[str, Any],
    loc: list[str],
    code: str,
) -> None:
    created = _create(api).json()

    response = api.patch(f"{PROPERTIES}/{created['id']}", json=body)

    assert response.status_code == 422
    error = response.json()["errors"][0]
    assert (error["loc"], error["code"]) == (loc, code)


def test_patch_to_a_taken_nickname_is_409(
    api: TestClient, owner: dict[str, Any]
) -> None:
    _create(api, nickname="Casa")
    other = _create(api, nickname="Playa").json()

    response = api.patch(f"{PROPERTIES}/{other['id']}", json={"nickname": "CASA"})

    assert response.status_code == 409
    assert response.json()["code"] == "property_name_taken"


def test_timezone_change_leaves_stored_readings_alone(
    api: TestClient, owner: dict[str, Any], probe: Probe
) -> None:
    created = _create(api).json()
    meter = api.post(
        f"{PROPERTIES}/{created['id']}/meters",
        json={"distributor": "EDESUR", "label": "Main"},
    ).json()
    probe.run(
        "INSERT INTO readings (id, meter_id, recorded_at, original_local_date,"
        " cumulative_kwh, source, status, created_by, created_at)"
        " VALUES (:id, :meter, '2026-10-01T04:00:00Z', '2026-10-01', 100, 'manual',"
        " 'valid', :user, '2026-10-01T04:00:00Z')",
        {"id": str(uuid4()), "meter": meter["id"], "user": owner["id"]},
    )
    before = probe.rows("SELECT recorded_at, original_local_date FROM readings")

    api.patch(f"{PROPERTIES}/{created['id']}", json={"timezone": "Asia/Tokyo"})

    assert probe.rows("SELECT recorded_at, original_local_date FROM readings") == before


def test_archive_hides_the_property_and_its_meters(
    api: TestClient, owner: dict[str, Any], probe: Probe
) -> None:
    created = _create(api).json()
    path = f"{PROPERTIES}/{created['id']}"
    meter = api.post(
        f"{path}/meters", json={"distributor": "EDESUR", "label": "Main"}
    ).json()

    assert api.delete(path).status_code == 204

    for response in (
        api.get(path),
        api.patch(path, json={"nickname": "Nueva"}),
        api.delete(path),
        api.get(f"{path}/meters"),
        api.post(f"{path}/meters", json={"distributor": "EDESUR", "label": "Two"}),
        api.get(f"/api/v1/meters/{meter['id']}"),
        api.patch(f"/api/v1/meters/{meter['id']}", json={"label": "X"}),
        api.post(f"/api/v1/meters/{meter['id']}/deactivate"),
    ):
        assert response.status_code == 404, response.request.url
        assert response.json()["code"] == "not_found"
    assert api.get(PROPERTIES).json()["items"] == []
    row = probe.rows("SELECT archived_at, updated_at FROM properties")[0]
    assert row["archived_at"] == row["updated_at"]
    assert [a["action"] for a in probe.audit(created["id"])] == [
        "property.create",
        "property.archive",
    ]


def test_other_owners_property_is_indistinguishable_from_a_missing_one(
    api: TestClient, owner: dict[str, Any], stranger: TestClient
) -> None:
    mine = _create(api).json()
    path = f"{PROPERTIES}/{mine['id']}"
    missing = f"{PROPERTIES}/{uuid4()}"

    requests: list[tuple[str, dict[str, Any] | None]] = [
        ("GET", None),
        ("PATCH", {"nickname": "Robada"}),
        ("DELETE", None),
    ]
    for method, body in requests:
        theirs = stranger.request(method, path, json=body)
        nowhere = stranger.request(method, missing, json=body)
        assert theirs.status_code == nowhere.status_code == 404
        assert without_request_id(theirs.json()) == without_request_id(nowhere.json())
    assert stranger.get(PROPERTIES).json()["items"] == []
    assert api.get(path).json()["nickname"] == "Casa"


def test_malformed_id_is_422(api: TestClient, owner: dict[str, Any]) -> None:
    response = api.get(f"{PROPERTIES}/not-a-uuid")

    assert response.status_code == 422
    assert response.json()["errors"][0]["loc"] == ["path", "property_id"]


class _Collect(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(self.format(record) + str(record.__dict__))


def test_conflicts_never_log_the_duplicate_value(
    api: TestClient, owner: dict[str, Any], new_client: Callable[[], TestClient]
) -> None:
    """PostgreSQL's DETAIL line names the value; it must never reach a log."""
    handler = _Collect()
    logger = logging.getLogger("energyiq")
    logger.addHandler(handler)
    try:
        _create(api, nickname="Secret Villa")
        assert _create(api, nickname="secret villa").status_code == 409
        taken = new_client().post(
            "/api/v1/auth/register",
            json={"email": "owner@example.test", "password": "correct horse battery"},
        )
        assert taken.status_code == 409
    finally:
        logger.removeHandler(handler)

    logged = "\n".join(handler.lines).lower()
    assert handler.lines  # access lines were written
    assert "secret villa" not in logged
    assert "owner@example.test" not in logged
    assert "detail" not in logged
