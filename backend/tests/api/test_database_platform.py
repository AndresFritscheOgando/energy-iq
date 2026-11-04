"""Database wiring that needs no running database (spec 0009/0001).

AC-5 and AC-6: a lazy engine, 503 for an unreachable database, and operational
errors mapped to 503 with a log line free of DSNs and SQL. AC-7: ``db`` tests
skip or fail by ``ENERGYIQ_REQUIRE_DB``. AC-8: prod requires its secrets.
"""

import logging
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from energyiq.main import create_app
from energyiq.platform.settings import Settings

CLOSED_PORT_DSN = (
    "postgresql+psycopg://energyiq_app:hunter2-synthetic@127.0.0.1:1/x_test"
)
REPO = Path(__file__).parents[3]


def _unreachable() -> Settings:
    return Settings(
        env="test",
        database_url=SecretStr(CLOSED_PORT_DSN),
        migration_database_url=SecretStr(CLOSED_PORT_DSN),
    )


def test_create_app_and_health_need_no_database() -> None:
    with TestClient(create_app(_unreachable())) as client:
        response = client.get("/health")

    assert response.status_code == 200


def test_readiness_answers_503_when_the_database_is_unreachable() -> None:
    with TestClient(create_app(_unreachable())) as client:
        started = time.perf_counter()
        response = client.get("/health/ready")
        elapsed = time.perf_counter() - started

    body = response.json()
    assert response.status_code == 503
    assert response.headers["content-type"] == "application/problem+json"
    assert body["code"] == "database_unavailable"
    assert body["detail"] == "The service is temporarily unavailable."
    assert response.headers["x-request-id"] == body["request_id"]
    assert "hunter2" not in response.text
    assert elapsed < 3.5


def test_lifespan_disposes_both_engines(monkeypatch: pytest.MonkeyPatch) -> None:
    app = create_app(_unreachable())
    disposed: list[str] = []
    for name in ("engine", "readiness_engine"):
        engine = getattr(app.state, name)
        monkeypatch.setattr(engine, "dispose", lambda name=name: disposed.append(name))

    with TestClient(app):
        assert disposed == []

    assert sorted(disposed) == ["engine", "readiness_engine"]


def _failing_app(exc: Exception) -> FastAPI:
    app = create_app(Settings(env="test"))

    @app.get("/_probe/fail")
    def fail() -> None:  # pyright: ignore[reportUnusedFunction]
        raise exc

    return app


OPERATIONAL = OperationalError(
    "SELECT password_hash FROM users WHERE email = %(email)s",
    {"email": "owner@example.test"},
    Exception("connection to 10.0.0.9 failed: user energyiq_app password hunter2"),
)


@pytest.mark.parametrize(
    "exc",
    [OPERATIONAL, PoolTimeoutError("QueuePool limit of size 5 overflow 10 reached")],
    ids=["operational", "pool_timeout"],
)
def test_operational_errors_answer_503_with_a_clean_log_line(
    exc: Exception, log_records: list[logging.LogRecord]
) -> None:
    app = _failing_app(exc)
    log_records.clear()

    response = TestClient(app).get("/_probe/fail")

    body = response.json()
    assert response.status_code == 503
    assert body == {
        "type": "about:blank",
        "title": "Service Unavailable",
        "status": 503,
        "detail": "The service is temporarily unavailable.",
        "code": "database_unavailable",
        "request_id": response.headers["x-request-id"],
    }
    errors = [r for r in log_records if r.name == "energyiq.errors"]
    assert len(errors) == 1
    assert errors[0].__dict__["request_id"] == body["request_id"]
    assert errors[0].exc_info is None
    rendered = " ".join(
        f"{r.getMessage()} {r.__dict__.get('access', '')}" for r in log_records
    )
    for secret in ("hunter2", "10.0.0.9", "password_hash", "owner@example.test"):
        assert secret not in rendered
        assert secret not in response.text


@pytest.mark.parametrize(
    "missing",
    ["ENERGYIQ_DATABASE_URL", "ENERGYIQ_MIGRATION_DATABASE_URL", "ENERGYIQ_SECRET_KEY"],
)
def test_prod_without_a_required_secret_fails_naming_it(
    monkeypatch: pytest.MonkeyPatch, prod_secrets: dict[str, str], missing: str
) -> None:
    monkeypatch.setenv("ENERGYIQ_ENV", "prod")
    monkeypatch.delenv(missing)

    with pytest.raises(ValidationError) as excinfo:
        create_app()

    errors = excinfo.value.errors()
    field = missing.removeprefix("ENERGYIQ_").lower()
    assert [(e["loc"], e["type"]) for e in errors] == [((field,), "missing")]


@pytest.mark.usefixtures("prod_secrets")
def test_prod_with_its_secrets_builds_the_app(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENERGYIQ_ENV", "prod")

    app = create_app()

    assert app.state.settings.env == "prod"


def test_secrets_never_render(prod_secrets: dict[str, str]) -> None:
    settings = Settings(env="prod")
    rendered = f"{settings!r} {settings} {settings.model_dump()}"

    for value in prod_secrets.values():
        assert value not in rendered


def _run_db_test(extra_env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("ENERGYIQ_")
    }
    env |= {
        "ENERGYIQ_MIGRATION_DATABASE_URL": CLOSED_PORT_DSN,
        "ENERGYIQ_DATABASE_URL": CLOSED_PORT_DSN,
    } | extra_env
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "backend/tests/db/test_schema.py::test_database_is_at_the_script_head",
        ],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def test_db_tests_skip_with_the_reason_when_the_database_is_unreachable() -> None:
    result = _run_db_test({})

    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 skipped" in result.stdout
    assert "PostgreSQL not reachable at 127.0.0.1:1/x_test" in result.stdout
    assert "hunter2" not in result.stdout


def test_require_db_turns_the_skip_into_a_failure() -> None:
    result = _run_db_test({"ENERGYIQ_REQUIRE_DB": "1"})

    assert result.returncode != 0
    assert "PostgreSQL not reachable at 127.0.0.1:1/x_test" in result.stdout
    assert "ENERGYIQ_REQUIRE_DB=1" in result.stdout


def test_db_tests_refuse_a_database_not_named_test() -> None:
    dev_dsn = CLOSED_PORT_DSN.removesuffix("x_test") + "energyiq_dev"
    result = _run_db_test(
        {"ENERGYIQ_MIGRATION_DATABASE_URL": dev_dsn, "ENERGYIQ_DATABASE_URL": dev_dsn}
    )

    assert result.returncode != 0
    assert "refusing to run db tests against 127.0.0.1:1/energyiq_dev" in result.stdout
    assert "hunter2" not in result.stdout
