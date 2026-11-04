"""Register, login, logout, sessions (spec 0009/0002 AC-1 to AC-4). Synthetic data."""

import hashlib
from collections.abc import Callable, Iterator
from http.cookies import SimpleCookie
from typing import Any
from uuid import UUID

import pytest
from argon2 import PasswordHasher
from dbsupport import CSRF, PASSWORD, Clock, Probe, without_request_id
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from energyiq.identity.passwords import PasswordService
from energyiq.main import create_app
from energyiq.platform.db import get_db_session
from energyiq.platform.settings import Settings

pytestmark = pytest.mark.db

Register = Callable[..., dict[str, Any]]
REGISTER = "/api/v1/auth/register"
LOGIN = "/api/v1/auth/login"
LOGOUT = "/api/v1/auth/logout"
ME = "/api/v1/auth/me"


def _cookie(response: Any, name: str = "energyiq_session") -> Any:
    jar = SimpleCookie()
    jar.load(response.headers["set-cookie"])
    return jar[name]


def _login(client: TestClient, email: str, password: str = PASSWORD) -> Any:
    return client.post(LOGIN, json={"email": email, "password": password})


# AC-1, AC-3, AC-4: the thin thread -------------------------------------------


def test_register_me_logout_me(api: TestClient, probe: Probe) -> None:
    register = api.post(
        REGISTER, json={"email": "owner@example.test", "password": PASSWORD}
    )

    assert register.status_code == 201
    user = register.json()
    assert set(user) == {"id", "email", "created_at"}
    assert user["email"] == "owner@example.test"
    assert user["created_at"] == "2026-11-04T12:00:00Z"

    me = api.get(ME)
    assert me.status_code == 200
    assert me.json() == user

    logout = api.post(LOGOUT)
    assert logout.status_code == 204
    assert 'energyiq_session=""' in logout.headers["set-cookie"]
    assert "Max-Age=0" in logout.headers["set-cookie"]

    after = api.get(ME)
    assert after.status_code == 401
    assert after.json()["code"] == "not_authenticated"
    assert "www-authenticate" not in after.headers
    actions = [row["action"] for row in probe.audit(user["id"])]
    assert actions == ["auth.register", "auth.logout"]


def test_session_cookie_attributes(api: TestClient) -> None:
    response = api.post(
        REGISTER, json={"email": "owner@example.test", "password": PASSWORD}
    )
    cookie = _cookie(response)
    header = response.headers["set-cookie"]

    assert cookie["httponly"] is True
    assert cookie["samesite"] == "lax"
    assert cookie["path"] == "/"
    assert cookie["max-age"] == "1209600"
    assert not cookie["secure"]
    assert "Domain" not in header


def test_only_the_token_hash_is_stored(api: TestClient, probe: Probe) -> None:
    response = api.post(
        REGISTER, json={"email": "owner@example.test", "password": PASSWORD}
    )
    token = _cookie(response).value

    stored = probe.rows("SELECT token_hash, expires_at, last_seen_at FROM sessions")
    assert len(stored) == 1
    assert bytes(stored[0]["token_hash"]) == hashlib.sha256(token.encode()).digest()
    assert len(token) >= 43  # 32 random bytes, base64url
    assert (
        probe.one(
            "SELECT count(*) FROM sessions WHERE encode(token_hash, 'escape') LIKE :t",
            {"t": f"%{token}%"},
        )
        == 0
    )
    password_hash = probe.one("SELECT password_hash FROM users")
    assert password_hash.startswith("$argon2id$")
    assert PASSWORD not in password_hash
    assert "password" not in response.text


def test_email_is_normalized(api: TestClient) -> None:
    response = api.post(
        REGISTER, json={"email": "  ＯＷＮＥＲ@Example.TEST ", "password": PASSWORD}
    )

    assert response.status_code == 201
    assert response.json()["email"] == "owner@example.test"


@pytest.mark.parametrize(
    ("body", "loc", "code"),
    [
        ({"email": "no-at-sign", "password": PASSWORD}, "email", "invalid_email"),
        ({"email": "a@b", "password": "short"}, "password", "password_length"),
        ({"email": 5, "password": PASSWORD}, "email", "invalid_type"),
    ],
)
def test_register_validation(
    api: TestClient, body: dict[str, Any], loc: str, code: str
) -> None:
    response = api.post(REGISTER, json=body)

    assert response.status_code == 422
    assert response.json()["errors"][0]["loc"] == ["body", loc]
    assert response.json()["errors"][0]["code"] == code


def test_register_rejects_server_owned_fields(api: TestClient) -> None:
    response = api.post(
        REGISTER, json={"email": "a@b.test", "password": PASSWORD, "id": "x"}
    )

    assert response.status_code == 422
    assert response.json()["errors"][0]["code"] == "unknown_field"


def test_duplicate_email_is_409_and_still_recorded(
    api: TestClient,
    register: Register,
    new_client: Callable[[], TestClient],
    probe: Probe,
) -> None:
    first = register(api)

    response = new_client().post(
        REGISTER, json={"email": "OWNER@example.test", "password": PASSWORD}
    )

    assert response.status_code == 409
    assert response.json()["code"] == "email_taken"
    assert "set-cookie" not in response.headers
    attempts = probe.rows(
        "SELECT succeeded FROM auth_attempts WHERE kind = 'register' ORDER BY id"
    )
    assert [row["succeeded"] for row in attempts] == [True, False]
    audits = probe.audit(first["id"])
    assert [(row["action"], row["metadata"]) for row in audits] == [
        ("auth.register", {}),
        ("auth.register", {"outcome": "email_taken"}),
    ]
    assert audits[1]["actor_user_id"] is None


# AC-2: login --------------------------------------------------------------------


def test_login_returns_the_user_and_a_new_session(
    api: TestClient,
    owner: dict[str, Any],
    new_client: Callable[[], TestClient],
    probe: Probe,
) -> None:
    other = new_client()
    response = _login(other, "owner@example.test")

    assert response.status_code == 200
    assert response.json() == owner
    assert other.get(ME).status_code == 200
    assert api.get(ME).status_code == 200  # the register session stays valid
    assert probe.one("SELECT count(*) FROM sessions") == 2
    assert [row["action"] for row in probe.audit(owner["id"])] == [
        "auth.register",
        "auth.login",
    ]


def test_login_revokes_the_session_cookie_it_was_sent_with(
    api: TestClient, owner: dict[str, Any], probe: Probe
) -> None:
    old_token = api.cookies["energyiq_session"]

    response = _login(api, "owner@example.test")

    new_token = _cookie(response).value
    assert new_token != old_token
    stale = TestClient(api.app, headers=CSRF, cookies={"energyiq_session": old_token})
    assert stale.get(ME).status_code == 401
    assert api.get(ME).status_code == 200
    revoked = probe.one("SELECT count(*) FROM sessions WHERE revoked_at IS NOT NULL")
    assert revoked == 1


@pytest.fixture
def verify_calls(
    db_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> Iterator[list[str]]:
    """Records each verification: ``dummy`` or ``real``."""
    passwords: PasswordService = db_app.state.passwords
    calls: list[str] = []
    real_verify = passwords.verify

    def spy(password_hash: str, password: str) -> bool:
        calls.append("dummy" if password_hash == passwords.dummy_hash else "real")
        return real_verify(password_hash, password)

    monkeypatch.setattr(passwords, "verify", spy)
    yield calls


def test_failed_logins_look_identical(
    api: TestClient,
    owner: dict[str, Any],
    new_client: Callable[[], TestClient],
    probe: Probe,
    verify_calls: list[str],
) -> None:
    disabled = new_client()
    disabled_user = disabled.post(
        REGISTER, json={"email": "gone@example.test", "password": PASSWORD}
    ).json()
    probe.run(
        "UPDATE users SET disabled_at = now() WHERE id = :id",
        {"id": disabled_user["id"]},
    )
    verify_calls.clear()

    unknown = _login(new_client(), "nobody@example.test")
    assert verify_calls == ["dummy"]
    wrong = _login(new_client(), "owner@example.test", "wrong password!!")
    gone = _login(new_client(), "gone@example.test")

    bodies = [without_request_id(r.json()) for r in (unknown, wrong, gone)]
    assert {r.status_code for r in (unknown, wrong, gone)} == {401}
    assert bodies[0] == bodies[1] == bodies[2]
    assert bodies[0]["code"] == "invalid_credentials"
    assert verify_calls == ["dummy", "real", "real"]
    assert all("set-cookie" not in r.headers for r in (unknown, wrong, gone))


def test_failed_login_leaves_attempt_and_audit_rows(
    api: TestClient, owner: dict[str, Any], probe: Probe
) -> None:
    response = _login(api, "owner@example.test", "wrong password!!")

    assert response.status_code == 401
    attempt = probe.rows("SELECT * FROM auth_attempts WHERE kind = 'login'")
    assert len(attempt) == 1
    assert attempt[0]["succeeded"] is False
    audit = probe.audit(owner["id"])[-1]
    assert audit["action"] == "auth.login_failed"
    assert audit["actor_user_id"] is None
    assert audit["metadata"] == {"reason": "wrong_password"}
    assert audit["request_id"] == response.headers["x-request-id"]


def test_unknown_email_failure_has_no_entity(api: TestClient, probe: Probe) -> None:
    _login(api, "nobody@example.test")

    audit = probe.rows(
        "SELECT entity_id, metadata FROM audit_events WHERE action = 'auth.login_failed'"
    )
    assert audit == [{"entity_id": None, "metadata": {"reason": "unknown_email"}}]


def test_login_rehashes_an_outdated_hash(
    api: TestClient, owner: dict[str, Any], probe: Probe
) -> None:
    outdated = PasswordHasher(time_cost=2, memory_cost=16, parallelism=1).hash(PASSWORD)
    probe.run("UPDATE users SET password_hash = :h", {"h": outdated})

    assert _login(api, "owner@example.test").status_code == 200

    stored = probe.one("SELECT password_hash FROM users")
    assert stored != outdated
    assert not api.app.state.passwords.needs_rehash(stored)  # type: ignore[attr-defined]
    assert _login(api, "owner@example.test").status_code == 200


def test_login_with_an_invalid_body_is_422(api: TestClient) -> None:
    response = api.post(LOGIN, json={"email": "owner@example.test"})

    assert response.status_code == 422
    assert response.json()["errors"][0]["loc"] == ["body", "password"]


# AC-3, AC-4: session validity ----------------------------------------------------


def _last_seen(probe: Probe) -> Any:
    return probe.one("SELECT last_seen_at FROM sessions")


def test_touch_waits_five_minutes(
    api: TestClient, owner: dict[str, Any], clock: Clock, probe: Probe
) -> None:
    created = _last_seen(probe)

    clock.advance(minutes=4, seconds=59)
    assert api.get(ME).status_code == 200
    assert _last_seen(probe) == created

    touched = clock.advance(seconds=1)
    assert api.get(ME).status_code == 200
    assert _last_seen(probe) == touched


def test_idle_timeout_is_strict(
    api: TestClient, owner: dict[str, Any], clock: Clock
) -> None:
    clock.advance(hours=24, microseconds=-1)
    assert api.get(ME).status_code == 200  # also touches last_seen_at

    clock.advance(hours=24)  # exactly 24 hours idle: no longer valid
    response = api.get(ME)
    assert response.status_code == 401
    assert response.json()["code"] == "not_authenticated"


def test_absolute_expiry_at_fourteen_days(
    api: TestClient, owner: dict[str, Any], clock: Clock
) -> None:
    for _ in range(14):
        clock.advance(hours=23, minutes=59)
        assert api.get(ME).status_code == 200
    clock.advance(minutes=13)  # 14 days minus 1 minute since login
    assert api.get(ME).status_code == 200

    clock.advance(minutes=1)  # now == expires_at: no longer valid
    assert api.get(ME).status_code == 401


def test_disabled_user_session_is_401(
    api: TestClient, owner: dict[str, Any], probe: Probe
) -> None:
    probe.run("UPDATE users SET disabled_at = now()")

    assert api.get(ME).status_code == 401


@pytest.mark.parametrize("cookie", ["", "not-a-real-token"])
def test_unknown_cookie_is_401(api: TestClient, cookie: str) -> None:
    api.cookies.set("energyiq_session", cookie)

    assert api.get(ME).status_code == 401


def test_logout_without_a_session_is_204_and_writes_nothing(
    api: TestClient, probe: Probe
) -> None:
    response = api.post(LOGOUT)

    assert response.status_code == 204
    assert "Max-Age=0" in response.headers["set-cookie"]
    assert probe.one("SELECT count(*) FROM audit_events") == 0


def test_revoked_session_is_401_after_logout_elsewhere(
    api: TestClient, owner: dict[str, Any]
) -> None:
    token = api.cookies["energyiq_session"]
    copy = TestClient(api.app, headers=CSRF, cookies={"energyiq_session": token})

    assert api.post(LOGOUT).status_code == 204
    assert copy.get(ME).status_code == 401


@pytest.fixture
def secure_client(db_session: Session) -> TestClient:
    """An https client for an app whose cookie is ``Secure``."""
    settings = Settings(env="test").model_copy(update={"session_cookie_secure": True})
    app = create_app(settings)

    def override() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_db_session] = override
    return TestClient(app, base_url="https://testserver", headers=CSRF)


def test_secure_cookie_uses_the_host_prefix(secure_client: TestClient) -> None:
    response = secure_client.post(
        REGISTER, json={"email": "owner@example.test", "password": PASSWORD}
    )

    assert response.status_code == 201
    cookie = _cookie(response, "__Host-energyiq_session")
    assert cookie["secure"] is True
    assert cookie["path"] == "/"
    assert "Domain" not in response.headers["set-cookie"]
    assert secure_client.get(ME).status_code == 200


def test_me_reads_the_current_user(api: TestClient, owner: dict[str, Any]) -> None:
    assert UUID(api.get(ME).json()["id"]) == UUID(owner["id"])
