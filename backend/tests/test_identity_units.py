"""Pure helpers of spec 0009/0002: normalization, limits, cursors, settings.

No database. Synthetic values only.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError
from pydantic_core import PydanticCustomError
from sqlalchemy.exc import IntegrityError

from energyiq.identity.passwords import PasswordService
from energyiq.identity.rate_limits import attempt_key, lock_key, retry_after
from energyiq.identity.schemas import normalize_email, normalize_password
from energyiq.platform import maintenance
from energyiq.platform.db import UnmappedIntegrityError, integrity_problem
from energyiq.platform.http.problems import ProblemError
from energyiq.platform.pagination import decode_cursor, encode_cursor
from energyiq.platform.settings import Settings

T0 = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("raw", "normalized"),
    [
        ("Owner@Example.TEST", "owner@example.test"),
        ("  owner@example.test\t", "owner@example.test"),
        ("ＯＷＮＥＲ@example.test", "owner@example.test"),  # NFKC folds full width
        ("a@b", "a@b"),
        ("x" * 240 + "@example.test", "x" * 240 + "@example.test"),  # 253 chars
    ],
)
def test_email_normalization(raw: str, normalized: str) -> None:
    assert normalize_email(raw) == normalized


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "owner",
        "@example.test",
        "owner@",
        "a@b@c",
        "own er@example.test",
        "x" * 242 + "@example.test",
    ],
)
def test_invalid_emails(raw: str) -> None:
    with pytest.raises(PydanticCustomError) as excinfo:
        normalize_email(raw)
    assert excinfo.value.type == "invalid_email"


@pytest.mark.parametrize("length", [12, 128])
def test_password_bounds_accept(length: int) -> None:
    assert normalize_password("p" * length) == "p" * length


@pytest.mark.parametrize("length", [0, 11, 129])
def test_password_bounds_reject(length: int) -> None:
    with pytest.raises(PydanticCustomError) as excinfo:
        normalize_password("p" * length)
    assert excinfo.value.type == "password_length"


def test_password_is_nfkc_normalized_before_counting() -> None:
    # "ﬁ" (one ligature character) becomes "fi" (two), so 11 + 1 → 13.
    assert normalize_password("p" * 11 + "ﬁ") == "p" * 11 + "fi"


def test_password_service_round_trip_and_rehash_flag() -> None:
    passwords = PasswordService("test")
    stored = passwords.hash("correct horse battery")

    assert passwords.verify(stored, "correct horse battery")
    assert not passwords.verify(stored, "wrong horse battery")
    assert not passwords.verify("not a hash", "anything at all")
    assert not passwords.needs_rehash(stored)
    assert PasswordService("dev").needs_rehash(stored)


def test_retry_after_uses_the_n_minus_l_plus_first_oldest() -> None:
    window = timedelta(minutes=15)
    counted = [T0 + timedelta(minutes=m) for m in range(7)]  # n = 7, L = 5
    now = T0 + timedelta(minutes=7)

    # The 3rd oldest (T0 + 2m) must leave before the count drops below 5.
    assert retry_after(counted, 5, window, now) == 600
    assert retry_after(counted[:4], 5, window, now) is None


def test_retry_after_is_at_least_one_second() -> None:
    counted = [T0]
    now = T0 + timedelta(minutes=15, microseconds=-1)

    assert retry_after(counted, 1, timedelta(minutes=15), now) == 1
    assert retry_after(counted, 1, timedelta(minutes=15), T0 + timedelta(hours=1)) == 1


def test_lock_key_is_a_signed_bigint_of_the_first_eight_bytes() -> None:
    key = bytes.fromhex("ff" * 8 + "00" * 24)

    assert lock_key(key) == -1
    assert lock_key(bytes(32)) == 0
    assert -(2**63) <= lock_key(attempt_key("secret", "owner@example.test")) < 2**63


def test_attempt_keys_depend_on_the_secret() -> None:
    assert attempt_key("one", "x") != attempt_key("two", "x")
    assert len(attempt_key("one", "x")) == 32


@pytest.mark.parametrize(
    "at", [T0, T0.replace(microsecond=1), T0.replace(microsecond=999_999)]
)
def test_cursor_round_trips_exactly(at: datetime) -> None:
    row_id = UUID("00000000-0000-4000-8000-000000000007")

    cursor = encode_cursor(at, row_id)
    key = decode_cursor(cursor)

    assert "=" not in cursor
    assert (key.at, key.id) == (at, row_id)


@pytest.mark.parametrize(
    "cursor",
    [
        "!!!",
        "a",
        "e30",  # {}
        "eyJrIjpbXX0",  # {"k":[]}
        "eyJrIjpbMSwyXX0",  # {"k":[1,2]}
        encode_cursor(T0, UUID(int=1)) + "AA",
        "x" * 300,
    ],
)
def test_invalid_cursors(cursor: str) -> None:
    with pytest.raises(PydanticCustomError) as excinfo:
        decode_cursor(cursor)
    assert excinfo.value.type == "invalid_cursor"


def test_cursor_rejects_a_non_canonical_timestamp() -> None:
    import base64
    import json

    payload = json.dumps({"k": ["2026-11-04T12:00:00.000000Z", str(UUID(int=1))]})
    cursor = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")

    with pytest.raises(PydanticCustomError):
        decode_cursor(cursor)


def test_session_and_origin_defaults_per_environment() -> None:
    dev = Settings(env="dev")
    assert dev.session_cookie_secure is False
    assert dev.trusted_origins == ["http://localhost:3000"]


@pytest.mark.usefixtures("prod_secrets")
def test_prod_cookie_is_secure_and_needs_trusted_origins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENERGYIQ_ENV", "prod")
    assert Settings().session_cookie_secure is True
    assert Settings().trusted_origins == ["https://app.example"]

    monkeypatch.setenv("ENERGYIQ_TRUSTED_ORIGINS", "[]")
    with pytest.raises(ValidationError) as excinfo:
        Settings()
    assert [(e["loc"], e["type"]) for e in excinfo.value.errors()] == [
        (("trusted_origins",), "missing")
    ]


@pytest.mark.usefixtures("prod_secrets")
def test_maintenance_missing_dsn_in_prod_exits_2_naming_the_field(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ENERGYIQ_ENV", "prod")
    monkeypatch.delenv("ENERGYIQ_MIGRATION_DATABASE_URL")

    assert maintenance.main() == 2

    error = capsys.readouterr().err
    assert "migration_database_url" in error
    assert "synthetic" not in error


class _Diag:
    def __init__(self, name: str | None) -> None:
        self.constraint_name = name


class _Orig(Exception):
    def __init__(self, name: str | None) -> None:
        super().__init__("DETAIL: Key (email)=(owner@example.test) already exists.")
        self.diag = _Diag(name)


def _integrity(name: str | None) -> IntegrityError:
    return IntegrityError("INSERT ...", {}, _Orig(name))


def test_integrity_problem_maps_known_constraint_names() -> None:
    problem = integrity_problem(_integrity("uq_x"), {"uq_x": (409, "x_taken")})

    assert isinstance(problem, ProblemError)
    assert (problem.status, problem.code) == (409, "x_taken")


@pytest.mark.parametrize("name", ["uq_other", None])
def test_unmapped_integrity_errors_carry_only_the_name(name: str | None) -> None:
    problem = integrity_problem(_integrity(name), {"uq_x": (409, "x_taken")})

    assert isinstance(problem, UnmappedIntegrityError)
    assert "owner@example.test" not in str(problem)
    assert str(name) in str(problem)
