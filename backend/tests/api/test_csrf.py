"""CSRF checks, route coverage, and check order (spec 0009/0002 AC-5, umbrella).

No database: 403 and the 401 for a missing cookie are decided before any
query, and the summary route runs with the synthetic signed in user.
"""

from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.dependencies.models import Dependant
from fastapi.routing import RouteContext, iter_route_contexts
from fastapi.testclient import TestClient

from energyiq.identity.dependencies import get_current_user
from energyiq.main import create_app
from energyiq.platform.http.csrf import UNSAFE_METHODS, own_origin, require_csrf
from energyiq.platform.settings import Settings

Body = Callable[..., dict[str, Any]]
SUMMARY = "/api/v1/consumption/summary"
PUBLIC = {"/api/v1/auth/register", "/api/v1/auth/login", "/api/v1/auth/logout"}


def _calls(dependant: Dependant) -> Iterator[object]:
    for dependency in dependant.dependencies:
        yield dependency.call
        yield from _calls(dependency)


def _api_routes(app: FastAPI) -> list[RouteContext]:
    """Effective routes: FastAPI 0.162 keeps included routers nested, and the
    effective dependant includes the router level dependencies."""
    return [
        route
        for route in iter_route_contexts(app.routes)
        if (route.path or "").startswith("/api/v1")
    ]


def test_every_unsafe_api_route_has_the_csrf_dependency() -> None:
    routes = _api_routes(create_app(Settings(env="test")))
    unsafe = [route for route in routes if (route.methods or set()) & UNSAFE_METHODS]

    assert len(unsafe) == 15
    for route in unsafe:
        assert require_csrf in set(_calls(route.dependant)), route.path


def test_every_api_route_but_register_login_logout_needs_a_session() -> None:
    routes = _api_routes(create_app(Settings(env="test")))

    for route in routes:
        needs = get_current_user in set(_calls(route.dependant))
        assert needs == (route.path not in PUBLIC), route.path


@pytest.fixture
def bare(app: FastAPI) -> TestClient:
    """No default CSRF header."""
    return TestClient(app)


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"X-EnergyIQ-CSRF": "0"},
        {"X-EnergyIQ-CSRF": "true"},
        {"X-EnergyIQ-CSRF": "1", "Origin": "http://evil.test"},
        {"X-EnergyIQ-CSRF": "1", "Origin": "null"},
        {"X-EnergyIQ-CSRF": "1", "Origin": "https://testserver"},
        {"X-EnergyIQ-CSRF": "1", "Origin": "http://testserver.evil.test"},
    ],
)
def test_rejected_requests_are_403(
    bare: TestClient, summary_body: Body, headers: dict[str, str]
) -> None:
    response = bare.post(SUMMARY, json=summary_body([]), headers=headers)

    assert response.status_code == 403
    assert response.json()["code"] == "csrf_rejected"
    assert response.json()["detail"] == "The request failed cross site request checks."


@pytest.mark.parametrize(
    "origin", [None, "http://testserver", "HTTP://TESTSERVER", "http://localhost:3000"]
)
def test_same_origin_trusted_or_absent_origin_passes(
    bare: TestClient, summary_body: Body, origin: str | None
) -> None:
    headers = {"X-EnergyIQ-CSRF": "1"}
    if origin is not None:
        headers["Origin"] = origin

    response = bare.post(SUMMARY, json=summary_body([]), headers=headers)

    assert response.status_code == 200


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/v1/auth/register"),
        ("POST", "/api/v1/auth/login"),
        ("POST", "/api/v1/auth/logout"),
        ("POST", "/api/v1/properties"),
        ("PATCH", "/api/v1/properties/00000000-0000-4000-8000-000000000001"),
        ("DELETE", "/api/v1/properties/00000000-0000-4000-8000-000000000001"),
        ("POST", "/api/v1/meters/00000000-0000-4000-8000-000000000001/deactivate"),
    ],
)
def test_public_and_private_unsafe_routes_need_the_header(
    bare: TestClient, method: str, path: str
) -> None:
    response = bare.request(method, path, json={})

    assert response.status_code == 403


def test_safe_methods_skip_the_check(bare: TestClient) -> None:
    assert (
        bare.get("/health", headers={"Origin": "http://evil.test"}).status_code == 200
    )


def test_a_configured_trusted_origin_passes(summary_body: Body) -> None:
    settings = Settings(env="test", trusted_origins=["https://app.example"])
    app = create_app(settings)
    app.dependency_overrides[get_current_user] = lambda: None
    response = TestClient(app).post(
        SUMMARY,
        json=summary_body([]),
        headers={"X-EnergyIQ-CSRF": "1", "Origin": "https://APP.example"},
    )

    assert response.status_code == 200


def test_own_origin_uses_the_scheme_and_host_header() -> None:
    app = FastAPI()
    seen: list[str] = []

    @app.get("/origin")
    def origin(request: Request) -> dict[str, str]:
        seen.append(own_origin(request))
        return {}

    TestClient(app, base_url="https://Example.test:8443").get("/origin")
    TestClient(app).get("/origin", headers={"X-Forwarded-Host": "evil.test"})

    assert seen == ["https://example.test:8443", "http://testserver"]


# Check order (umbrella): 403 → 415 → 401 → 422 -----------------------------------


@pytest.fixture
def anonymous() -> TestClient:
    """The real auth dependency with no cookie: 401 without a query."""
    return TestClient(create_app(Settings(env="test")))


def test_403_before_415(anonymous: TestClient) -> None:
    response = anonymous.post(
        SUMMARY, content=b"x", headers={"Content-Type": "text/plain"}
    )

    assert response.status_code == 403


def test_415_before_401(anonymous: TestClient) -> None:
    response = anonymous.post(
        SUMMARY,
        content=b"x",
        headers={"Content-Type": "text/plain", "X-EnergyIQ-CSRF": "1"},
    )

    assert response.status_code == 415


def test_401_before_422(anonymous: TestClient) -> None:
    response = anonymous.post(
        SUMMARY, json={"bogus": 1}, headers={"X-EnergyIQ-CSRF": "1"}
    )

    assert response.status_code == 401
    assert response.json()["code"] == "not_authenticated"


def test_401_on_reads_without_a_session(anonymous: TestClient) -> None:
    for path in ("/api/v1/auth/me", "/api/v1/properties"):
        response = anonymous.get(path)
        assert response.status_code == 401
        assert "www-authenticate" not in response.headers


def test_malformed_json_may_answer_before_403(anonymous: TestClient) -> None:
    """FastAPI parses JSON before dependencies run (accepted, umbrella)."""
    response = anonymous.post(
        SUMMARY, content=b"{", headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 400
    assert response.json()["code"] == "malformed_json"
