"""Maintenance purge and committed security records (spec 0009/0002 AC-2, AC-11).

These tests commit to the test database, because the purge and a real
request use their own connections. Each one removes what it wrote.
"""

import hashlib
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from dbsupport import CSRF, PASSWORD
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from energyiq.main import create_app
from energyiq.platform import maintenance
from energyiq.platform.settings import Settings

pytestmark = pytest.mark.db_commit

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


@pytest.fixture
def seeded(migrator_engine: Engine) -> Iterator[dict[str, list[object]]]:
    """Old and fresh attempts and sessions for one synthetic user."""
    user_id = uuid4()
    ids: dict[str, list[object]] = {"old": [], "fresh": []}
    marker = uuid4().bytes + uuid4().bytes  # 32 bytes, unique to this test
    with migrator_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users (id, email, password_hash, created_at)"
                " VALUES (:id, :email, 'x', :now)"
            ),
            {"id": user_id, "email": f"purge-{user_id.hex}@example.test", "now": NOW},
        )
        for age, bucket in (
            (timedelta(hours=24, seconds=1), "old"),
            (timedelta(hours=23), "fresh"),
        ):
            attempt_id = connection.execute(
                text(
                    "INSERT INTO auth_attempts (kind, client_key, succeeded, attempted_at)"
                    " VALUES ('login', :key, false, :at) RETURNING id"
                ),
                {"key": marker, "at": NOW - age},
            ).scalar_one()
            ids[bucket].append(attempt_id)
        sessions = [
            ("old", NOW - timedelta(days=31), None),  # expired 31 days ago
            (
                "old",
                NOW + timedelta(days=1),
                NOW - timedelta(days=31),
            ),  # revoked long ago
            ("fresh", NOW - timedelta(days=29), None),  # expired recently
            ("fresh", NOW + timedelta(days=1), NOW - timedelta(days=1)),
            ("fresh", NOW + timedelta(days=1), None),  # active
        ]
        for bucket, expires_at, revoked_at in sessions:
            session_id = uuid4()
            connection.execute(
                text(
                    "INSERT INTO sessions (id, user_id, token_hash, created_at,"
                    " last_seen_at, expires_at, revoked_at)"
                    " VALUES (:id, :user, :hash, :at, :at, :expires, :revoked)"
                ),
                {
                    "id": session_id,
                    "user": user_id,
                    "hash": hashlib.sha256(session_id.bytes).digest(),
                    "at": expires_at - timedelta(days=14),
                    "expires": expires_at,
                    "revoked": revoked_at,
                },
            )
            ids[bucket].append(session_id)
    yield ids
    with migrator_engine.begin() as connection:
        connection.execute(
            text("DELETE FROM auth_attempts WHERE client_key = :k"), {"k": marker}
        )
        connection.execute(
            text("DELETE FROM sessions WHERE user_id = :u"), {"u": user_id}
        )
        connection.execute(text("DELETE FROM users WHERE id = :u"), {"u": user_id})


def _remaining(engine: Engine, ids: list[object]) -> set[object]:
    with engine.connect() as connection:
        attempts = connection.execute(
            text("SELECT id FROM auth_attempts WHERE id = ANY(:ids)"),
            {"ids": [i for i in ids if isinstance(i, int)]},
        ).scalars()
        sessions = connection.execute(
            text("SELECT id FROM sessions WHERE id = ANY(:ids)"),
            {"ids": [i for i in ids if isinstance(i, UUID)]},
        ).scalars()
        return set(attempts) | set(sessions)


def test_purge_deletes_only_expired_rows(
    migrator_engine: Engine, seeded: dict[str, list[object]]
) -> None:
    counts = maintenance.purge(migrator_engine, NOW)

    assert set(counts) == {"auth_attempts", "sessions"}
    assert counts["auth_attempts"] >= 1
    assert counts["sessions"] >= 2
    assert _remaining(migrator_engine, seeded["old"]) == set()
    assert _remaining(migrator_engine, seeded["fresh"]) == set(seeded["fresh"])


def test_main_prints_counts_only(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    seeded: dict[str, list[object]],
) -> None:
    monkeypatch.setenv("ENERGYIQ_ENV", "test")
    monkeypatch.setattr(maintenance, "get_now", lambda: NOW)

    assert maintenance.main() == 0

    lines = capsys.readouterr().out.splitlines()
    assert [line.split(":")[0] for line in lines] == ["auth_attempts", "sessions"]
    assert all(line.split(": ")[1].isdigit() for line in lines)


def test_failed_login_rows_are_committed_before_the_401(
    db_settings: Settings,
    migrator_engine: Engine,
    delete_committed_user: Callable[[str, datetime], None],
) -> None:
    """Against the real engine: nothing rolls the security rows back."""
    started = datetime.now(UTC)
    email = f"commit-{uuid4().hex}@example.test"
    client = TestClient(create_app(db_settings), headers=CSRF)
    try:
        assert (
            client.post(
                "/api/v1/auth/register", json={"email": email, "password": PASSWORD}
            ).status_code
            == 201
        )
        failed = client.post(
            "/api/v1/auth/login", json={"email": email, "password": "wrong password!!"}
        )
        assert failed.status_code == 401
        with migrator_engine.connect() as connection:
            attempts = (
                connection.execute(
                    text(
                        "SELECT succeeded FROM auth_attempts WHERE kind = 'login'"
                        " AND attempted_at >= :since"
                    ),
                    {"since": started},
                )
                .scalars()
                .all()
            )
            audit = (
                connection.execute(
                    text("SELECT action FROM audit_events WHERE request_id = :rid"),
                    {"rid": failed.headers["x-request-id"]},
                )
                .scalars()
                .all()
            )
        assert attempts == [False]
        assert audit == ["auth.login_failed"]
    finally:
        delete_committed_user(email, started)
