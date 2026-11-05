"""``Cache-Control: no-store`` on every auth response (spec 0010 AC-13).

Each route is driven down a path that needs no database: ``me`` without a
cookie (401), ``logout`` without a session (204), and ``login`` and
``register`` with an invalid body (422).
"""

import pytest
from fastapi.testclient import TestClient

from energyiq.main import create_app
from energyiq.platform.http.csrf import CSRF_HEADER
from energyiq.platform.settings import Settings


@pytest.fixture
def anonymous() -> TestClient:
    return TestClient(create_app(Settings(env="test")), headers={CSRF_HEADER: "1"})


@pytest.mark.parametrize(
    ("method", "path", "status"),
    [
        ("GET", "/api/v1/auth/me", 401),
        ("POST", "/api/v1/auth/logout", 204),
        ("POST", "/api/v1/auth/login", 422),
        ("POST", "/api/v1/auth/register", 422),
    ],
)
def test_auth_responses_are_no_store(
    anonymous: TestClient, method: str, path: str, status: int
) -> None:
    response = anonymous.request(method, path, json={})

    assert response.status_code == status
    assert response.headers["cache-control"] == "no-store"


def test_csrf_rejection_is_no_store() -> None:
    client = TestClient(create_app(Settings(env="test")))

    response = client.post("/api/v1/auth/logout")

    assert response.status_code == 403
    assert response.headers["cache-control"] == "no-store"


def test_other_routes_are_not_marked(anonymous: TestClient) -> None:
    assert "cache-control" not in anonymous.get("/health").headers
