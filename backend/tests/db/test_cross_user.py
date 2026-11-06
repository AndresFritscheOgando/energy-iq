"""Cross user and list isolation matrices (spec 0009/0004 AC-1, AC-2). Synthetic data.

The matrices are tables keyed by ``(method, path template)``. A coverage test
compares them with the routes the app actually serves, so a new id route or
list route without a matrix row fails the build.
"""

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import pytest
from dbsupport import Holdings, Probe, TwoUsers, created, without_request_id
from fastapi.testclient import TestClient
from routesupport import ApiRoute, api_routes
from sqlalchemy import Connection, text

from energyiq.main import create_app
from energyiq.platform.settings import Settings

V1 = "/api/v1"


@dataclass(frozen=True)
class Call:
    json: dict[str, Any] | None = None
    params: dict[str, str] = field(default_factory=dict[str, str])


WINDOW = {"from": "2026-11-01T00:00:00Z", "to": "2026-11-03T00:00:00Z"}

# Every route with an id in its path, with a body and query that pass
# validation, so the request reaches the ownership check.
ID_ROUTES: dict[tuple[str, str], Call] = {
    ("GET", f"{V1}/properties/{{property_id}}"): Call(),
    ("PATCH", f"{V1}/properties/{{property_id}}"): Call({"nickname": "Taken"}),
    ("DELETE", f"{V1}/properties/{{property_id}}"): Call(),
    ("POST", f"{V1}/properties/{{property_id}}/meters"): Call(
        {"distributor": "EDESUR", "label": "Taken"}
    ),
    ("GET", f"{V1}/properties/{{property_id}}/meters"): Call(),
    ("GET", f"{V1}/meters/{{meter_id}}"): Call(),
    ("PATCH", f"{V1}/meters/{{meter_id}}"): Call({"label": "Taken"}),
    ("POST", f"{V1}/meters/{{meter_id}}/deactivate"): Call(),
    ("POST", f"{V1}/meters/{{meter_id}}/readings"): Call(
        {"recorded_at": "2026-11-03T12:00:00Z", "cumulative_kwh": "105"}
    ),
    ("GET", f"{V1}/meters/{{meter_id}}/readings"): Call(),
    ("PATCH", f"{V1}/meters/{{meter_id}}/readings/{{reading_id}}"): Call(
        {"status": "flagged"}
    ),
    ("POST", f"{V1}/meters/{{meter_id}}/events"): Call(
        {"event_type": "calibration", "effective_at": "2026-11-03T12:00:00Z"}
    ),
    ("GET", f"{V1}/meters/{{meter_id}}/events"): Call(),
    ("POST", f"{V1}/meters/{{meter_id}}/events/{{event_id}}/approve"): Call(),
    ("POST", f"{V1}/meters/{{meter_id}}/events/{{event_id}}/reject"): Call(),
    ("GET", f"{V1}/meters/{{meter_id}}/consumption"): Call(params=WINDOW),
    ("POST", f"{V1}/meters/{{meter_id}}/invoices"): Call({}),
    ("GET", f"{V1}/meters/{{meter_id}}/invoices"): Call(),
    ("GET", f"{V1}/invoices/{{invoice_id}}"): Call(),
    ("POST", f"{V1}/invoices/{{invoice_id}}/revisions"): Call(
        {
            "base_revision_id": str(uuid4()),
            "expected_current_revision_id": str(uuid4()),
            "total_dop": "1",
        }
    ),
    ("POST", f"{V1}/invoices/{{invoice_id}}/confirm"): Call(
        {"draft_revision_id": str(uuid4()), "expected_current_revision_id": None}
    ),
    # Spec 0012/0002: the upload route answers 404 before it reads the body.
    ("POST", f"{V1}/meters/{{meter_id}}/documents"): Call(),
    ("GET", f"{V1}/documents/{{document_id}}"): Call(),
    ("GET", f"{V1}/documents/{{document_id}}/source"): Call(),
    ("GET", f"{V1}/documents/{{document_id}}/extractions"): Call(),
    ("POST", f"{V1}/documents/{{document_id}}/retry"): Call(),
    ("DELETE", f"{V1}/documents/{{document_id}}"): Call(),
}

# Every paginated list: the attribute of ``Holdings`` naming its parent id
# (``None`` for top level lists).
LIST_ROUTES: dict[tuple[str, str], str | None] = {
    ("GET", f"{V1}/properties"): None,
    ("GET", f"{V1}/properties/{{property_id}}/meters"): "property_id",
    ("GET", f"{V1}/meters/{{meter_id}}/readings"): "meter_id",
    ("GET", f"{V1}/meters/{{meter_id}}/events"): "meter_id",
    ("GET", f"{V1}/meters/{{meter_id}}/invoices"): "meter_id",
}


def _app_routes() -> list[ApiRoute]:
    return api_routes(create_app(Settings(env="test")))


# Coverage: the tables above match the app (no database needed) ---------------


def test_every_id_route_is_in_the_cross_user_matrix() -> None:
    served = {route.key for route in _app_routes() if route.has_id}

    assert served == set(ID_ROUTES)


def test_every_list_route_is_in_the_isolation_matrix() -> None:
    served = {route.key for route in _app_routes() if "page_params" in route.calls}

    assert served == set(LIST_ROUTES)


# AC-1: another owner's ids are indistinguishable from nonexistent ones -------


def _snapshot(connection: Connection) -> dict[str, Any]:
    """Row count and a content digest per table, plus the latest audit id."""
    tables = connection.execute(
        text(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
            " AND tablename <> 'alembic_version' ORDER BY tablename"
        )
    ).scalars()
    state: dict[str, Any] = {}
    for table in list(tables):
        state[table] = connection.execute(
            text(
                f"SELECT count(*), md5(coalesce(string_agg(t::text, '|'"
                f" ORDER BY t::text), '')) FROM {table} t"
            )
        ).one()
    state["max_audit_id"] = connection.execute(
        text("SELECT max(id) FROM audit_events")
    ).scalar_one()
    return state


def _send(
    client: TestClient,
    key: tuple[str, str],
    ids: dict[str, str],
    headers: dict[str, str] | None = None,
) -> Any:
    method, template = key
    call = ID_ROUTES[key]
    return client.request(
        method,
        template.format(**{**_random_ids(), **ids}),
        json=call.json,
        params=call.params,
        headers=headers,
    )


def _random_ids() -> dict[str, str]:
    return {
        name: str(uuid4())
        for name in (
            "property_id",
            "meter_id",
            "reading_id",
            "event_id",
            "invoice_id",
            "document_id",
        )
    }


def _mixed_ids(own: Holdings, other: Holdings) -> dict[str, str]:
    """The caller's own meter with the other owner's reading and event."""
    return {**other.ids(), "property_id": own.property_id, "meter_id": own.meter_id}


def _expect_hidden(
    client: TestClient,
    key: tuple[str, str],
    ids: dict[str, str],
    connection: Connection,
    headers: dict[str, str] | None = None,
) -> None:
    baseline = _send(client, key, _random_ids())
    unknown = client.get(f"{V1}/no-such-resource/{uuid4()}")
    before = _snapshot(connection)

    response = _send(client, key, ids, headers)

    assert response.status_code == 404, response.text
    assert response.json()["code"] == "not_found"
    assert without_request_id(response.json()) == without_request_id(baseline.json())
    assert without_request_id(response.json()) == without_request_id(unknown.json())
    assert _snapshot(connection) == before


@pytest.mark.db
@pytest.mark.parametrize("key", list(ID_ROUTES), ids=" ".join)
def test_b_cannot_reach_a_through_any_id_route(
    two_users: TwoUsers, db_connection: Connection, key: tuple[str, str]
) -> None:
    _expect_hidden(two_users.b.client, key, two_users.a.ids(), db_connection)


@pytest.mark.db
@pytest.mark.parametrize(
    "key",
    [key for key in ID_ROUTES if "{reading_id}" in key[1] or "{event_id}" in key[1]],
    ids=" ".join,
)
def test_b_cannot_reach_a_child_through_its_own_meter(
    two_users: TwoUsers, db_connection: Connection, key: tuple[str, str]
) -> None:
    ids = _mixed_ids(two_users.b, two_users.a)
    _expect_hidden(two_users.b.client, key, ids, db_connection)


@pytest.mark.db
@pytest.mark.parametrize(
    "key", [key for key in ID_ROUTES if key[0] == "POST"], ids=" ".join
)
def test_a_retry_key_does_not_leak_across_owners(
    two_users: TwoUsers, db_connection: Connection, key: tuple[str, str]
) -> None:
    """A key sent with a foreign id never leaves an idempotency row behind."""
    headers = {"Idempotency-Key": f"cross-{uuid4().hex}"}
    _expect_hidden(two_users.b.client, key, two_users.a.ids(), db_connection, headers)


@pytest.mark.db
@pytest.mark.parametrize("key", list(ID_ROUTES), ids=" ".join)
def test_an_archived_property_hides_everything_under_it(
    two_users: TwoUsers, db_connection: Connection, key: tuple[str, str]
) -> None:
    _expect_hidden(two_users.a.client, key, two_users.archived.ids(), db_connection)


# AC-2: lists only ever return the caller's rows ------------------------------


@dataclass
class Owned:
    """Ids an owner created, per list route."""

    holdings: Holdings
    rows: dict[tuple[str, str], set[str]] = field(
        default_factory=dict[tuple[str, str], set[str]]
    )


def _grow(holdings: Holdings, tag: str) -> Owned:
    """Add rows to every list: two more properties, meters, readings, events."""
    client = holdings.client
    meter_path = f"{V1}/meters/{holdings.meter_id}"
    properties = {holdings.property_id} | {
        created(client.post(f"{V1}/properties", json={"nickname": f"{tag} {n}"}))
        for n in range(2)
    }
    meters = {holdings.meter_id} | {
        created(
            client.post(
                f"{V1}/properties/{holdings.property_id}/meters",
                json={"distributor": "EDESUR", "label": f"{tag} {n}"},
            )
        )
        for n in range(2)
    }
    readings = {holdings.reading_id} | {
        created(
            client.post(
                f"{meter_path}/readings",
                json={
                    "recorded_at": f"2026-11-0{day}T12:00:00Z",
                    "cumulative_kwh": str(100 + day),
                },
            )
        )
        for day in (2, 3)
    }
    events = {holdings.event_id} | {
        created(
            client.post(
                f"{meter_path}/events",
                json={
                    "event_type": "calibration",
                    "effective_at": f"2026-11-0{day}T06:00:00Z",
                },
            )
        )
        for day in (2, 3)
    }
    invoices = {
        created(
            client.post(f"{meter_path}/invoices", json={"total_dop": str(100 + index)})
        )
        for index in range(3)
    }
    keys = list(LIST_ROUTES)
    return Owned(
        holdings,
        dict(zip(keys, (properties, meters, readings, events, invoices), strict=True)),
    )


def _listed(client: TestClient, path: str) -> Iterator[str]:
    """Every id across all pages, two items per page."""
    params: dict[str, str] = {"limit": "2"}
    while True:
        response = client.get(path, params=params)
        assert response.status_code == 200, response.text
        page = response.json()
        yield from (item["id"] for item in page["items"])
        if page["next_cursor"] is None:
            return
        params["cursor"] = page["next_cursor"]


def _list_path(key: tuple[str, str], holdings: Holdings) -> str:
    parent = LIST_ROUTES[key]
    return (
        key[1]
        if parent is None
        else key[1].format(**{parent: getattr(holdings, parent)})
    )


@pytest.mark.db
def test_lists_return_only_the_callers_rows(two_users: TwoUsers, probe: Probe) -> None:
    a = _grow(two_users.a, "A")
    b = _grow(two_users.b, "B")

    for key in LIST_ROUTES:
        for mine, theirs in ((a, b), (b, a)):
            listed = list(_listed(mine.holdings.client, _list_path(key, mine.holdings)))
            assert len(listed) == len(set(listed)), key
            assert set(listed) == mine.rows[key], key
            assert not set(listed) & theirs.rows[key], key
    # A's archived property and its rows exist but are listed nowhere.
    assert (
        probe.one("SELECT count(*) FROM properties WHERE archived_at IS NOT NULL") == 1
    )
    assert two_users.archived.property_id not in a.rows[("GET", f"{V1}/properties")]
