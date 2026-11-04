"""Settings driven docs and CORS: AC-11."""

from typing import Literal

import httpx2
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.middleware.cors import CORSMiddleware

from energyiq.main import create_app
from energyiq.platform.settings import Settings

PATH = "/api/v1/consumption/summary"
DOC_PATHS = ("/docs", "/redoc", "/openapi.json")


def _preflight(client: TestClient, origin: str) -> httpx2.Response:
    return client.options(
        PATH,
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type, X-Request-ID",
        },
    )


def test_create_app_without_env_fails_naming_it() -> None:
    with pytest.raises(ValidationError) as excinfo:
        create_app()

    assert [(e["loc"], e["type"]) for e in excinfo.value.errors()] == [
        (("env",), "missing")
    ]


def test_invalid_setting_fails_create_app_naming_the_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENERGYIQ_ENV", "staging")

    with pytest.raises(ValidationError) as excinfo:
        create_app()

    assert excinfo.value.errors()[0]["loc"] == ("env",)


@pytest.mark.usefixtures("prod_secrets")
@pytest.mark.parametrize("path", DOC_PATHS)
def test_prod_hides_docs(path: str) -> None:
    client = TestClient(create_app(Settings(env="prod")))

    response = client.get(path)

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


@pytest.mark.parametrize("env", ["dev", "test"])
@pytest.mark.parametrize("path", DOC_PATHS)
def test_dev_and_test_serve_docs(env: Literal["dev", "test"], path: str) -> None:
    client = TestClient(create_app(Settings(env=env)))

    assert client.get(path).status_code == 200


@pytest.mark.usefixtures("prod_secrets")
def test_prod_installs_no_cors_middleware() -> None:
    app = create_app(Settings(env="prod"))

    assert all(m.cls is not CORSMiddleware for m in app.user_middleware)
    response = TestClient(app).get(
        "/health", headers={"Origin": "http://localhost:3000"}
    )
    assert "access-control-allow-origin" not in response.headers


def test_empty_origins_in_dev_install_no_cors_middleware() -> None:
    app = create_app(Settings(env="dev", cors_origins=[]))

    assert all(m.cls is not CORSMiddleware for m in app.user_middleware)


def test_allowed_preflight_without_credentials(client: TestClient) -> None:
    response = _preflight(client, "http://localhost:3000")

    assert response.status_code == 200
    headers = response.headers
    assert headers["access-control-allow-origin"] == "http://localhost:3000"
    assert set(headers["access-control-allow-methods"].split(", ")) == {
        "GET",
        "POST",
        "PATCH",
        "DELETE",
    }
    for name in ("X-Request-ID", "X-EnergyIQ-CSRF", "Idempotency-Key"):
        assert name in headers["access-control-allow-headers"]
    assert "access-control-allow-credentials" not in headers


def test_allowed_simple_request_exposes_request_id(client: TestClient) -> None:
    response = client.get("/health", headers={"Origin": "http://localhost:3000"})

    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert response.headers["access-control-expose-headers"] == (
        "X-Request-ID, Retry-After, Idempotent-Replayed"
    )
    assert "access-control-allow-credentials" not in response.headers


def test_disallowed_origin_never_gets_allow_origin(client: TestClient) -> None:
    preflight = _preflight(client, "http://evil.test")
    simple = client.get("/health", headers={"Origin": "http://evil.test"})

    assert preflight.status_code == 400
    assert "access-control-allow-origin" not in preflight.headers
    assert simple.status_code == 200
    assert "access-control-allow-origin" not in simple.headers


@pytest.mark.usefixtures("prod_secrets")
def test_configured_origins_replace_the_default() -> None:
    client = TestClient(
        create_app(Settings(env="prod", cors_origins=["https://app.example"]))
    )

    allowed = client.get("/health", headers={"Origin": "https://app.example"})
    local = client.get("/health", headers={"Origin": "http://localhost:3000"})

    assert allowed.headers["access-control-allow-origin"] == "https://app.example"
    assert "access-control-allow-origin" not in local.headers
