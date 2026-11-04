"""Request and response models for the auth routes (spec 0009/0002 AC-1, AC-2)."""

import unicodedata
from typing import Annotated
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict
from pydantic_core import PydanticCustomError

MAX_EMAIL_LENGTH = 254
MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 128

_REQUEST_CONFIG = ConfigDict(extra="forbid", frozen=True)


def normalize_email(value: str) -> str:
    """NFKC, trim, lowercase; one ``@`` with both sides non empty, no
    whitespace, at most 254 characters."""
    email = unicodedata.normalize("NFKC", value).strip().lower()
    local, at, domain = email.partition("@")
    if (
        not at
        or not local
        or not domain
        or "@" in domain
        or any(char.isspace() for char in email)
        or len(email) > MAX_EMAIL_LENGTH
    ):
        raise PydanticCustomError("invalid_email", "Value must be an email address.")
    return email


def normalize_password(value: str) -> str:
    """NFKC, then 12 to 128 characters. No composition rules."""
    password = unicodedata.normalize("NFKC", value)
    if not MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH:
        raise PydanticCustomError(
            "password_length", "Password must be 12 to 128 characters."
        )
    return password


Email = Annotated[str, AfterValidator(normalize_email)]
Password = Annotated[str, AfterValidator(normalize_password)]


class CredentialsIn(BaseModel):
    """Body of register and login."""

    model_config = _REQUEST_CONFIG

    email: Email
    password: Password


class UserOut(BaseModel):
    """The signed in account; never carries the password hash."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    email: str
    created_at: str
