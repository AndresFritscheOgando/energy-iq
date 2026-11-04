"""Unauthenticated and CSRF matrices (spec 0009/0004 AC-3, AC-4). Synthetic data.

Both matrices take their route list from the app, so a new route is covered
the moment it is served.
"""

import secrets
from collections.abc import Callable
from typing import Any
from uuid import uuid4

import pytest
from dbsupport import START, Clock, Probe
from fastapi.testclient import TestClient
from routesupport import PUBLIC, UNSAFE, ApiRoute, api_routes

from energyiq.main import create_app
from energyiq.platform.settings import Settings

COOKIE = "energyiq_session"
ROUTES = api_routes(create_app(Settings(env="test")))
PRIVATE = [route for route in ROUTES if route.path not in PUBLIC]
UNSAFE_ROUTES = [route for route in ROUTES if route.method in UNSAFE]


def _path(route: ApiRoute) -> str:
    return route.path.format(
        property_id=uuid4(), meter_id=uuid4(), reading_id=uuid4(), event_id=uuid4()
    )


def _send(client: TestClient, route: ApiRoute, **kwargs: Any) -> Any:
    """A well formed request; JSON routes get ``{}`` so 415 never answers first."""
    body: dict[str, Any] | None = {} if "require_json" in route.calls else None
    return client.request(route.method, _path(route), json=body, **kwargs)


def test_the_matrices_cover_every_api_route() -> None:
    assert {route.path for route in ROUTES} - {
        route.path for route in PRIVATE
    } == PUBLIC
    assert PRIVATE
    assert UNSAFE_ROUTES


# AC-3: every private route answers 401 for every unusable credential ---------

Credential = Callable[[TestClient, Probe, Clock], str | None]


def _no_cookie(_client: TestClient, _probe: Probe, _clock: Clock) -> str | None:
    return None


def _malformed(_client: TestClient, _probe: Probe, _clock: Clock) -> str | None:
    return "not a token!"


def _unknown(_client: TestClient, _probe: Probe, _clock: Clock) -> str | None:
    return secrets.token_urlsafe(32)


def _signed_in(client: TestClient) -> str:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": f"matrix-{uuid4().hex[:8]}@example.test",
            "password": "correct horse battery",
        },
    )
    assert response.status_code == 201, response.text
    return client.cookies[COOKIE]


def _revoked(client: TestClient, _probe: Probe, _clock: Clock) -> str | None:
    token = _signed_in(client)
    assert client.post("/api/v1/auth/logout").status_code == 204
    return token


def _expired(client: TestClient, probe: Probe, clock: Clock) -> str | None:
    """Kept active past the 14 day absolute expiry (touched daily, never idle)."""
    token = _signed_in(client)
    for _ in range(15):
        clock.advance(hours=23)
        client.get("/api/v1/auth/me")
    return token


def _disabled(client: TestClient, probe: Probe, _clock: Clock) -> str | None:
    token = _signed_in(client)
    probe.run("UPDATE users SET disabled_at = :now", {"now": START})
    return token


CREDENTIALS: dict[str, Credential] = {
    "no cookie": _no_cookie,
    "malformed cookie": _malformed,
    "unknown token": _unknown,
    "revoked session": _revoked,
    "expired session": _expired,
    "disabled user": _disabled,
}


@pytest.mark.db
@pytest.mark.parametrize("credential", list(CREDENTIALS))
def test_every_private_route_rejects_the_credential(
    api: TestClient, probe: Probe, clock: Clock, credential: str
) -> None:
    token = CREDENTIALS[credential](api, probe, clock)
    failures: list[str] = []

    for route in PRIVATE:
        api.cookies.clear()
        if token is not None:
            api.cookies.set(COOKIE, token)
        response = _send(api, route)
        if (
            response.status_code != 401
            or response.json().get("code") != "not_authenticated"
        ):
            failures.append(
                f"{route.method} {route.path}: {response.status_code} {response.text}"
            )

    assert failures == []


# AC-4: every unsafe route answers 403 without the header or from a foreign origin
# (the CSRF check runs before any query, so no database is needed).


@pytest.fixture(scope="module")
def bare() -> TestClient:
    return TestClient(create_app(Settings(env="test")))


@pytest.mark.parametrize(
    "headers",
    [{}, {"X-EnergyIQ-CSRF": "1", "Origin": "http://evil.test"}],
    ids=["no header", "foreign origin"],
)
@pytest.mark.parametrize("route", UNSAFE_ROUTES, ids=lambda r: f"{r.method} {r.path}")
def test_every_unsafe_route_rejects_cross_site_requests(
    bare: TestClient, route: ApiRoute, headers: dict[str, str]
) -> None:
    response = _send(bare, route, headers=headers)

    assert response.status_code == 403, response.text
    assert response.json()["code"] == "csrf_rejected"
