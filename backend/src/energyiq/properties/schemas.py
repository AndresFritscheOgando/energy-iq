"""Request and response models for properties and meters (spec 0009/0002 AC-7, AC-8).

Request models forbid unknown fields, so server owned fields (``id``,
``owner_user_id``, ``active``, timestamps) cannot be sent. PATCH fields may
be omitted; only ``region`` and ``register_digits`` may be set to ``null``.
"""

from typing import Annotated, Self
from uuid import UUID

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    model_validator,
)
from pydantic_core import PydanticCustomError

from energyiq.platform.http.types import IanaTimezone, reject_null, trimmed
from energyiq.properties.models import DEFAULT_TIMEZONE, Distributor

MAX_REGION_LENGTH = 80
MIN_REGISTER_DIGITS = 4
MAX_REGISTER_DIGITS = 9

_REQUEST_CONFIG = ConfigDict(extra="forbid", frozen=True)
_RESPONSE_CONFIG = ConfigDict(frozen=True)


def _region(value: str | None) -> str | None:
    """Trimmed, at most 80 characters; an empty string means no region."""
    if value is None:
        return None
    value = value.strip()
    if len(value) > MAX_REGION_LENGTH:
        raise PydanticCustomError("invalid_text_length", "Text length is out of range.")
    return value or None


def _register_digits(value: object) -> object:
    """A JSON integer 4 to 9, or ``null``; no strings, floats, or booleans."""
    if value is None:
        return None
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not MIN_REGISTER_DIGITS <= value <= MAX_REGISTER_DIGITS
    ):
        raise PydanticCustomError(
            "invalid_register_digits", "Value must be an integer from 4 to 9."
        )
    return value


Nickname = Annotated[str, trimmed(1, 80)]
Label = Annotated[str, trimmed(1, 60)]
Region = Annotated[str | None, AfterValidator(_region)]
RegisterDigits = Annotated[int | None, BeforeValidator(_register_digits)]
NotNull = BeforeValidator(reject_null)


def _require_a_field(model: BaseModel) -> None:
    if not model.model_fields_set:
        raise PydanticCustomError("empty_patch", "Give at least one field to change.")


class PropertyCreate(BaseModel):
    model_config = _REQUEST_CONFIG

    nickname: Nickname
    region: Region = None
    timezone: IanaTimezone = DEFAULT_TIMEZONE


class PropertyPatch(BaseModel):
    model_config = _REQUEST_CONFIG

    nickname: Annotated[Nickname | None, NotNull] = None
    region: Region = None
    timezone: Annotated[IanaTimezone | None, NotNull] = None

    @model_validator(mode="after")
    def _not_empty(self) -> Self:
        _require_a_field(self)
        return self


class PropertyOut(BaseModel):
    model_config = _RESPONSE_CONFIG

    id: UUID
    nickname: str
    region: str | None
    timezone: str
    created_at: str
    updated_at: str


class MeterCreate(BaseModel):
    model_config = _REQUEST_CONFIG

    distributor: Distributor
    label: Label
    register_digits: RegisterDigits = None


class MeterPatch(BaseModel):
    model_config = _REQUEST_CONFIG

    label: Annotated[Label | None, NotNull] = None
    register_digits: RegisterDigits = None

    @model_validator(mode="after")
    def _not_empty(self) -> Self:
        _require_a_field(self)
        return self


class MeterOut(BaseModel):
    model_config = _RESPONSE_CONFIG

    id: UUID
    property_id: UUID
    distributor: Distributor
    label: str
    register_digits: int | None
    active: bool
    deactivated_at: str | None
    created_at: str
    updated_at: str
