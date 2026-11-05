import pytest
from pydantic import ValidationError

from energyiq.platform.settings import Settings

ENV_VARS = (
    "ENERGYIQ_ENV",
    "ENERGYIQ_MAX_BODY_BYTES",
    "ENERGYIQ_CORS_ORIGINS",
    "ENERGYIQ_LOG_LEVEL",
)


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def test_env_is_required() -> None:
    with pytest.raises(ValidationError) as excinfo:
        Settings()

    assert [(e["loc"], e["type"]) for e in excinfo.value.errors()] == [
        (("env",), "missing")
    ]


def test_dev_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENERGYIQ_ENV", "dev")

    settings = Settings()

    assert settings.env == "dev"
    assert settings.max_body_bytes == 1_048_576
    assert settings.cors_origins == ["http://localhost:3000"]
    assert settings.log_level == "INFO"


def test_test_env_keeps_local_cors_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENERGYIQ_ENV", "test")

    assert Settings().cors_origins == ["http://localhost:3000"]


@pytest.mark.usefixtures("prod_secrets")
def test_prod_defaults_to_no_cors_origins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENERGYIQ_ENV", "prod")

    assert Settings().cors_origins == []


@pytest.mark.usefixtures("prod_secrets")
def test_explicit_cors_origins_override_env_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENERGYIQ_ENV", "prod")
    monkeypatch.setenv("ENERGYIQ_CORS_ORIGINS", '["http://a.test"]')

    assert Settings().cors_origins == ["http://a.test"]


def test_explicit_empty_cors_origins_are_kept_in_dev(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENERGYIQ_ENV", "dev")
    monkeypatch.setenv("ENERGYIQ_CORS_ORIGINS", "[]")

    assert Settings().cors_origins == []


def test_values_are_read_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENERGYIQ_ENV", "dev")
    monkeypatch.setenv("ENERGYIQ_MAX_BODY_BYTES", "2048")
    monkeypatch.setenv("ENERGYIQ_LOG_LEVEL", "DEBUG")

    settings = Settings()

    assert settings.max_body_bytes == 2048
    assert settings.log_level == "DEBUG"


@pytest.mark.parametrize(
    ("name", "value", "field"),
    [
        ("ENERGYIQ_ENV", "staging", "env"),
        ("ENERGYIQ_ENV", "Dev", "env"),
        ("ENERGYIQ_MAX_BODY_BYTES", "0", "max_body_bytes"),
        ("ENERGYIQ_MAX_BODY_BYTES", "-1", "max_body_bytes"),
        ("ENERGYIQ_LOG_LEVEL", "TRACE", "log_level"),
    ],
)
def test_invalid_values_fail_naming_the_field(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str, field: str
) -> None:
    monkeypatch.setenv("ENERGYIQ_ENV", "dev")
    monkeypatch.setenv(name, value)

    with pytest.raises(ValidationError) as excinfo:
        Settings()

    assert excinfo.value.errors()[0]["loc"] == (field,)


@pytest.mark.parametrize("env", ["dev", "test"])
def test_forwarded_allow_ips_default_to_loopback(env: str) -> None:
    settings = Settings(env=env)  # pyright: ignore[reportArgumentType]

    assert settings.forwarded_allow_ips == ["127.0.0.1", "::1"]


@pytest.mark.usefixtures("prod_secrets")
def test_prod_requires_forwarded_allow_ips(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENERGYIQ_ENV", "prod")
    monkeypatch.delenv("ENERGYIQ_FORWARDED_ALLOW_IPS")

    with pytest.raises(ValidationError) as excinfo:
        Settings()

    assert [(e["loc"], e["type"]) for e in excinfo.value.errors()] == [
        (("forwarded_allow_ips",), "missing")
    ]


@pytest.mark.usefixtures("prod_secrets")
def test_prod_accepts_an_explicit_empty_allow_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENERGYIQ_ENV", "prod")
    monkeypatch.setenv("ENERGYIQ_FORWARDED_ALLOW_IPS", "[]")

    assert Settings().forwarded_allow_ips == []


def test_forwarded_allow_ips_read_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENERGYIQ_ENV", "dev")
    monkeypatch.setenv("ENERGYIQ_FORWARDED_ALLOW_IPS", '["10.0.0.5", "10.1.0.0/16"]')

    assert Settings().forwarded_allow_ips == ["10.0.0.5", "10.1.0.0/16"]


@pytest.mark.parametrize("entry", ["nextjs.internal", "*", "10.0.0.300", "10.0.0.1/40"])
def test_forwarded_allow_ips_reject_non_addresses(entry: str) -> None:
    with pytest.raises(ValidationError) as excinfo:
        Settings(env="dev", forwarded_allow_ips=[entry])

    assert excinfo.value.errors()[0]["loc"] == ("forwarded_allow_ips",)


def test_settings_are_frozen() -> None:
    settings = Settings(env="dev")

    with pytest.raises(ValidationError):
        settings.env = "prod"  # type: ignore[misc]
