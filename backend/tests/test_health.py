import pytest
from fastapi.testclient import TestClient

from energyiq import __version__
from energyiq.main import create_app
from energyiq.platform.settings import Settings


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(Settings(env="test")))


def test_health_returns_ok_and_version(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {"status": "ok", "version": __version__}


def test_health_rejects_post(client: TestClient) -> None:
    response = client.post("/health")

    assert response.status_code == 405


def test_create_app_builds_independent_apps() -> None:
    first = create_app(Settings(env="test"))
    second = create_app(Settings(env="test"))

    assert first is not second


def test_create_app_keeps_given_settings() -> None:
    settings = Settings(env="test", max_body_bytes=2048)

    app = create_app(settings)

    assert app.state.settings is settings


@pytest.mark.usefixtures("prod_secrets")
def test_create_app_reads_environment_when_settings_omitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENERGYIQ_ENV", "prod")

    app = create_app()

    assert app.state.settings.env == "prod"
