"""Auth rate limits (spec 0009/0002 AC-6). Synthetic data only."""

import hashlib
import hmac
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest
from dbsupport import PASSWORD, Clock, Probe
from fastapi import FastAPI
from fastapi.testclient import TestClient

from energyiq.platform.http.csrf import CSRF_HEADER
from energyiq.platform.settings import LOCAL_SECRET_KEY

pytestmark = pytest.mark.db

Register = Callable[..., dict[str, Any]]
LOGIN = "/api/v1/auth/login"
REGISTER = "/api/v1/auth/register"
EMAIL = "owner@example.test"


def _login(
    client: TestClient, email: str = EMAIL, password: str = "wrong password!!"
) -> Any:
    return client.post(LOGIN, json={"email": email, "password": password})


def _hmac(value: str) -> bytes:
    return hmac.new(LOCAL_SECRET_KEY.encode(), value.encode(), hashlib.sha256).digest()


def test_fifth_failure_locks_the_email(
    api: TestClient, owner: dict[str, Any], clock: Clock, probe: Probe
) -> None:
    first = clock.now
    for _ in range(5):
        assert _login(api).status_code == 401
        clock.advance(minutes=1)

    refused = _login(api)
    right_password = _login(api, password=PASSWORD)

    assert refused.status_code == 429
    assert refused.json()["code"] == "too_many_attempts"
    # The oldest counted failure leaves the 15 minute window at first + 15m.
    expected = int((first + timedelta(minutes=15) - clock.now).total_seconds())
    assert refused.headers["retry-after"] == str(expected) == "600"
    assert right_password.status_code == 429
    assert probe.one("SELECT count(*) FROM auth_attempts WHERE kind = 'login'") == 5


def test_the_lock_lifts_when_a_failure_leaves_the_window(
    api: TestClient, owner: dict[str, Any], clock: Clock
) -> None:
    for _ in range(5):
        _login(api)
    clock.advance(minutes=15)

    assert _login(api, password=PASSWORD).status_code == 200


def test_retry_after_rounds_up_and_is_at_least_one(
    api: TestClient, owner: dict[str, Any], clock: Clock
) -> None:
    for _ in range(5):
        _login(api)
    clock.advance(minutes=14, seconds=59, microseconds=500_000)

    assert _login(api).headers["retry-after"] == "1"


def test_success_resets_the_email_counter(
    api: TestClient, owner: dict[str, Any], clock: Clock
) -> None:
    for _ in range(4):
        assert _login(api).status_code == 401
    clock.advance(seconds=1)
    assert _login(api, password=PASSWORD).status_code == 200
    clock.advance(seconds=1)
    for _ in range(4):
        assert _login(api).status_code == 401

    assert _login(api).status_code == 401  # 5th failure since the success
    assert _login(api).status_code == 429


def test_twenty_logins_from_one_client_lock_the_client(
    api: TestClient, probe: Probe
) -> None:
    for index in range(20):
        assert _login(api, f"user{index}@example.test").status_code == 401

    refused = _login(api, "fresh@example.test")

    assert refused.status_code == 429
    assert int(refused.headers["retry-after"]) == 900
    assert probe.one("SELECT count(*) FROM auth_attempts") == 20


def test_client_limit_counts_successes_too(
    api: TestClient, owner: dict[str, Any]
) -> None:
    # The register attempt is not a login attempt, so 20 logins fit.
    for _ in range(20):
        assert _login(api, password=PASSWORD).status_code == 200

    assert _login(api, password=PASSWORD).status_code == 429


def test_fifth_register_attempt_locks_the_client(
    api: TestClient, register: Register, clock: Clock, probe: Probe
) -> None:
    register(api)
    for index in range(3):
        register(api, f"user{index}@example.test")
    taken = api.post(REGISTER, json={"email": EMAIL, "password": PASSWORD})
    assert taken.status_code == 409  # failed attempts count as well

    refused = api.post(
        REGISTER, json={"email": "late@example.test", "password": PASSWORD}
    )

    assert refused.status_code == 429
    assert refused.headers["retry-after"] == "3600"
    assert probe.one("SELECT count(*) FROM auth_attempts WHERE kind = 'register'") == 5

    clock.advance(hours=1)
    register(api, "late@example.test")


def test_invalid_bodies_are_rejected_before_counting(
    api: TestClient, probe: Probe
) -> None:
    for _ in range(6):
        assert (
            api.post(REGISTER, json={"email": "bad", "password": PASSWORD}).status_code
            == 422
        )

    assert probe.one("SELECT count(*) FROM auth_attempts") == 0


def test_attempt_rows_hold_keys_not_raw_values(
    api: TestClient, owner: dict[str, Any], probe: Probe
) -> None:
    _login(api)

    rows = probe.rows(
        "SELECT kind, email_key, client_key FROM auth_attempts ORDER BY id"
    )
    register_row, login_row = rows
    assert register_row["kind"] == "register"
    assert register_row["email_key"] is None
    assert bytes(login_row["email_key"]) == _hmac(EMAIL)
    assert bytes(login_row["client_key"]) == _hmac("testclient")
    for row in rows:
        stored = bytes(row["client_key"]) + bytes(row["email_key"] or b"")
        assert b"testclient" not in stored
        assert EMAIL.encode() not in stored
    audit_text = str(probe.rows("SELECT metadata FROM audit_events"))
    assert EMAIL not in audit_text
    assert "testclient" not in audit_text


def test_forwarded_clients_behind_the_proxy_get_separate_buckets(
    db_app: FastAPI, clock: Clock, probe: Probe
) -> None:
    """Spec 0010 AC-14: a trusted proxy peer supplies each browser's address
    in ``X-Forwarded-For``, so one browser's register limit never blocks
    another. The Next.js rewrite does not add that address itself; it comes
    from an edge proxy (``ENERGYIQ_EDGE_PROXY=true``, spec 0010 AC-18)."""
    proxy = TestClient(db_app, headers={CSRF_HEADER: "1"}, client=("127.0.0.1", 50000))

    def from_browser(address: str, email: str) -> int:
        return proxy.post(
            REGISTER,
            json={"email": email, "password": PASSWORD},
            headers={"X-Forwarded-For": address},
        ).status_code

    for index in range(5):
        assert from_browser("198.51.100.1", f"a{index}@example.test") == 201
    assert from_browser("198.51.100.1", "a5@example.test") == 429

    assert from_browser("198.51.100.2", "b0@example.test") == 201
    keys = probe.one(
        "SELECT count(DISTINCT client_key) FROM auth_attempts WHERE kind = 'register'"
    )
    assert keys == 2
    assert (
        probe.one(
            "SELECT count(*) FROM auth_attempts WHERE client_key = :key",
            {"key": _hmac("198.51.100.2")},
        )
        == 1
    )
