"""The refusals that make the demo password and the database reset safe
(spec 0011 child 0003 AC-2, AC-8, AC-9, AC-10). No test here sends a real request."""

import importlib.util
import itertools
import json
from collections.abc import Callable
from datetime import date
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx2
import pytest

SCRIPTS = Path(__file__).parents[1] / "scripts"


def _load(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(
        f"scripts_{name}", SCRIPTS / f"{name}.py"
    )
    assert spec is not None and spec.loader is not None
    module: ModuleType = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


seed = _load("seed_demo")
reset = _load("reset_e2e_db")

DEV = {"ENERGYIQ_ENV": "dev"}
TODAY = date(2026, 11, 5)


def _never_called(request: httpx2.Request) -> httpx2.Response:
    raise AssertionError(f"no request may be sent: {request.url}")


def _problem(status: int, code: str, **headers: str) -> httpx2.Response:
    return httpx2.Response(status, json={"code": code}, headers=headers)


def _run(
    handler: Callable[[httpx2.Request], httpx2.Response],
    env: dict[str, str] | None = None,
    argv: list[str] | None = None,
) -> int:
    return seed.run(
        argv or [],
        DEV if env is None else env,
        transport=httpx2.MockTransport(handler),
        today=lambda: TODAY,
    )


@pytest.mark.parametrize(
    "env", [{}, {"ENERGYIQ_ENV": "prod"}, {"ENERGYIQ_ENV": "staging"}]
)
def test_seed_refuses_other_environments_with_no_request(
    env: dict[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run(_never_called, env=env) == 1
    assert "ENERGYIQ_ENV" in capsys.readouterr().out


@pytest.mark.parametrize(
    "url",
    [
        "http://example.test:8000",
        "http://10.0.0.5:8000",
        "http://127.0.0.1.example.test",
        "https://localhost.evil.test",
    ],
)
def test_seed_refuses_a_non_loopback_api_with_no_request(
    url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run(_never_called, argv=["--api-url", url]) == 1
    assert "127.0.0.1" in capsys.readouterr().out


@pytest.mark.parametrize(
    "url", ["http://127.0.0.1:8000", "http://localhost:8100", "http://[::1]:8000"]
)
def test_seed_accepts_loopback(url: str) -> None:
    seed.check_target(url, DEV)


def test_email_taken_after_a_failed_login_explains_the_password(
    capsys: pytest.CaptureFixture[str],
) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("/login"):
            return _problem(401, "invalid_credentials")
        return _problem(409, "email_taken")

    assert _run(handler) == 1
    out = capsys.readouterr().out
    assert "different password" in out
    assert "recreate the database" in out


def test_short_password_says_how_long(capsys: pytest.CaptureFixture[str]) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("/login"):
            return _problem(401, "invalid_credentials")
        return _problem(422, "validation_failed")

    assert _run(handler, env={**DEV, "ENERGYIQ_DEMO_PASSWORD": "short"}) == 1
    assert "12 to 128 characters" in capsys.readouterr().out


def test_rate_limit_prints_the_wait_and_does_not_retry(
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(request.url.path)
        return httpx2.Response(
            429, json={"code": "too_many_attempts"}, headers={"Retry-After": "600"}
        )

    assert _run(handler) == 1
    assert "600 seconds" in capsys.readouterr().out
    assert calls == ["/api/v1/auth/login"]


def test_seed_content_and_rerun_archives_first(
    capsys: pytest.CaptureFixture[str],
) -> None:
    deleted: list[str] = []
    readings: list[dict[str, str]] = []
    keys: set[str] = set()

    def handler(request: httpx2.Request) -> httpx2.Response:
        path = request.url.path
        assert request.headers["X-EnergyIQ-CSRF"] == "1"
        if path.endswith("/login"):
            return httpx2.Response(
                200, json={}, headers={"Set-Cookie": "energyiq_session=SECRET"}
            )
        if request.method == "GET":
            return httpx2.Response(
                200, json={"items": [{"id": "old"}], "next_cursor": None}
            )
        if request.method == "DELETE":
            deleted.append(path)
            return httpx2.Response(204)
        keys.add(request.headers["Idempotency-Key"])
        if path.endswith("/readings"):
            readings.append(json.loads(request.content))
            return httpx2.Response(201, json={"id": "r"})
        return httpx2.Response(201, json={"id": "new"})

    assert _run(handler) == 0
    assert deleted == ["/api/v1/properties/old"]
    assert len(keys) == len(seed.READINGS) + 2
    assert readings[0] == {"local_date": "2026-01-09", "cumulative_kwh": "12400"}
    assert readings[-1] == {"local_date": "2026-11-02", "cumulative_kwh": "14872"}
    out = capsys.readouterr().out
    assert seed.DEMO_EMAIL in out
    assert seed.DEFAULT_PASSWORD in out
    assert "SECRET" not in out


def test_seed_readings_tell_the_listed_stories() -> None:
    days = [day for day, _ in seed.READINGS]
    values = [float(value) for _, value in seed.READINGS]
    assert days == sorted(days, reverse=True)
    assert days[0] >= 295
    assert 3 <= days[-1] <= 5
    gaps = [left - right for left, right in itertools.pairwise(days)]
    assert max(gaps) == 42
    drops = [i for i in range(1, len(values)) if values[i] < values[i - 1]]
    assert [days[i] for i in drops] == [70]


@pytest.mark.parametrize(
    "name", ["energyiq_dev", "energyiq_test", "postgres", "energyiq_e2e2"]
)
def test_reset_refuses_any_other_database(
    name: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def explode(*_: object, **__: object) -> None:
        raise AssertionError("nothing may be dropped")

    monkeypatch.setattr(reset, "recreate", explode)
    monkeypatch.setattr(reset, "migrate", explode)
    assert reset.main(["--database", name]) == 2
    assert "refusing" in capsys.readouterr().out


def test_reset_print_urls_names_only_the_target(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("ENERGYIQ_MIGRATION_DATABASE_URL", raising=False)
    assert reset.main(["--database", "energyiq_e2e", "--print-urls"]) == 0
    urls = json.loads(capsys.readouterr().out)
    assert set(urls) == {"app", "migrator"}
    assert all(url.rsplit("/", 1)[1] == "energyiq_e2e" for url in urls.values())
