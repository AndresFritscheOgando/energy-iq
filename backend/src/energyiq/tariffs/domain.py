"""Validated tariff schedules and the deterministic BTS-1 energy calculator.

Spec 0012 child 0006. This is data, not executable rules: a schedule is a list
of bands copied from an official SIE resolution, and the calculator applies
them with exact ``Decimal`` arithmetic. Nothing here knows a rate; every value
comes from a checked manifest. Anything the schedule does not settle returns an
:class:`Abstention` with a reason code, never a guess.

Band semantics (the checked source must say which applies, so each band names it):

- ``energy_slice``: the kWh in ``(from_kwh, to_kwh]`` cost ``amount`` DOP per kWh.
  The first slice starts at 0 and each slice starts where the last ended. Only
  the last slice may be open ended (``to_kwh`` None).
- ``energy_all_kwh``: when billed kWh reach ``from_kwh``, every kWh costs
  ``amount``. It must be the last energy band.
- ``fixed_range``: billed kWh inside ``[from_kwh, to_kwh]`` (``to_kwh`` None is
  open ended) carry a fixed charge of ``amount`` DOP.

Billed kWh that fall between two published ranges (for example 700.5 when one
range ends at 700 and the next starts at 701) are not priced.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import (
    ROUND_DOWN,
    ROUND_HALF_EVEN,
    ROUND_HALF_UP,
    ROUND_UP,
    Context,
    Decimal,
    Inexact,
    localcontext,
)
from enum import StrEnum
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)
from pydantic_core import PydanticCustomError

SUPPORTED_DISTRIBUTORS = ("EDESUR", "EDEESTE", "EDENORTE")
SUPPORTED_CLASS = "BTS-1"
MAX_AMOUNT = Decimal(1000000)
AMOUNT_PLACES = 6
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_ARITHMETIC = Context(prec=40)


class Distributor(StrEnum):
    EDESUR = "EDESUR"
    EDEESTE = "EDEESTE"
    EDENORTE = "EDENORTE"


class RoundingMode(StrEnum):
    HALF_UP = "half_up"
    HALF_EVEN = "half_even"
    UP = "up"
    DOWN = "down"


_MODES = {
    RoundingMode.HALF_UP: ROUND_HALF_UP,
    RoundingMode.HALF_EVEN: ROUND_HALF_EVEN,
    RoundingMode.UP: ROUND_UP,
    RoundingMode.DOWN: ROUND_DOWN,
}


class RoundingScope(StrEnum):
    TOTAL = "total"
    PER_BAND = "per_band"


class ChargeType(StrEnum):
    ENERGY_SLICE = "energy_slice"
    ENERGY_ALL_KWH = "energy_all_kwh"
    FIXED_RANGE = "fixed_range"


def _exact_decimal(value: object) -> Decimal:
    """A decimal string only: a float or int would hide a binary approximation."""
    if isinstance(value, Decimal):
        return value
    if not isinstance(value, str):
        raise PydanticCustomError("decimal_string", "Use a decimal string.")
    try:
        parsed = Decimal(value.strip())
    except ArithmeticError:
        raise PydanticCustomError("decimal_string", "Use a decimal string.") from None
    if not parsed.is_finite():
        raise PydanticCustomError("decimal_string", "Use a finite decimal.")
    return parsed


Amount = Annotated[
    Decimal,
    BeforeValidator(_exact_decimal),
    Field(ge=0, le=MAX_AMOUNT, decimal_places=AMOUNT_PLACES),
]
Kwh = Annotated[
    Decimal,
    BeforeValidator(_exact_decimal),
    Field(ge=0, le=Decimal(999999999999), decimal_places=AMOUNT_PLACES),
]


class TariffBand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    charge_type: ChargeType
    from_kwh: Kwh
    to_kwh: Kwh | None = None
    amount: Amount

    @model_validator(mode="after")
    def range_order(self) -> "TariffBand":
        if self.charge_type is ChargeType.ENERGY_ALL_KWH and self.to_kwh is not None:
            raise PydanticCustomError(
                "band_range", "An all kWh band has no upper bound."
            )
        if self.to_kwh is None:
            return self
        single_point = (
            self.charge_type is ChargeType.FIXED_RANGE and self.to_kwh == self.from_kwh
        )
        if self.to_kwh <= self.from_kwh and not single_point:
            raise PydanticCustomError("band_range", "A band must end after it starts.")
        return self


class Rounding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    places: Annotated[int, Field(ge=0, le=6)]
    mode: RoundingMode
    scope: RoundingScope


def _check_bands(bands: Sequence[TariffBand]) -> None:
    energy = [b for b in bands if b.charge_type is not ChargeType.FIXED_RANGE]
    fixed = [b for b in bands if b.charge_type is ChargeType.FIXED_RANGE]
    if not energy:
        raise PydanticCustomError("no_energy_band", "Add at least one energy band.")
    previous_to = Decimal(0)
    seen_all = False
    for index, band in enumerate(energy):
        if seen_all:
            raise PydanticCustomError(
                "band_order", "An all kWh band must be the last energy band."
            )
        if band.charge_type is ChargeType.ENERGY_SLICE:
            if band.from_kwh != previous_to:
                raise PydanticCustomError(
                    "band_order", "Each slice must start where the previous one ended."
                )
            if band.to_kwh is None:
                if index != len(energy) - 1:
                    raise PydanticCustomError(
                        "band_order", "Only the last slice may be open ended."
                    )
            else:
                previous_to = band.to_kwh
        else:
            seen_all = True
            if band.from_kwh < previous_to or (
                index > 0 and energy[index - 1].to_kwh is None
            ):
                raise PydanticCustomError(
                    "band_order", "An all kWh band must start at or after the slices."
                )
    expected = Decimal(0)
    for index, band in enumerate(fixed):
        if index == 0 and band.from_kwh != 0:
            raise PydanticCustomError("fixed_order", "Fixed ranges start at 0 kWh.")
        if index > 0 and band.from_kwh <= expected:
            raise PydanticCustomError("fixed_order", "Fixed ranges cannot overlap.")
        if band.to_kwh is None and index != len(fixed) - 1:
            raise PydanticCustomError(
                "fixed_order", "Only the last fixed range may be open ended."
            )
        if band.to_kwh is not None:
            expected = band.to_kwh


def _https_sie(value: str) -> str:
    parts = urlsplit(value)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not (
        host == "sie.gob.do" or host.endswith(".sie.gob.do")
    ):
        raise PydanticCustomError(
            "source_url", "The source must be an https sie.gob.do URL."
        )
    if parts.username or parts.password or parts.fragment:
        raise PydanticCustomError(
            "source_url", "The source URL cannot carry credentials."
        )
    return value


class TariffSchedule(BaseModel):
    """One checked rule: scope, dates, source, bands, and rounding."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    distributor: Distributor
    tariff_class: Literal["BTS-1"]
    effective_start: date
    effective_end: date
    resolution_id: Annotated[
        str, Field(pattern=r"^SIE-[0-9]{1,4}-[0-9]{4}(-[A-Z]{1,6})?$")
    ]
    source_url: Annotated[str, Field(max_length=500), BeforeValidator(_https_sie)]
    source_digest: str
    published_on: date
    checked_on: date
    checked_by: Annotated[str, Field(min_length=2, max_length=120)]
    rounding: Rounding
    bands: Annotated[tuple[TariffBand, ...], Field(min_length=1, max_length=40)]

    @field_validator("source_digest")
    @classmethod
    def digest(cls, value: str) -> str:
        if not _DIGEST.match(value):
            raise PydanticCustomError(
                "source_digest", "The digest must be 64 lowercase hex characters."
            )
        return value

    @field_validator("checked_by")
    @classmethod
    def checked_by_is_named(cls, value: str) -> str:
        if value != value.strip() or "@" in value:
            raise PydanticCustomError(
                "checked_by", "Name the reviewer without an email address."
            )
        return value

    @model_validator(mode="after")
    def consistent(self) -> "TariffSchedule":
        if self.effective_end < self.effective_start:
            raise PydanticCustomError(
                "effective_order", "The rule must end on or after it starts."
            )
        if self.checked_on < self.published_on:
            raise PydanticCustomError(
                "checked_order", "The source cannot be checked before it was published."
            )
        _check_bands(self.bands)
        return self

    def covers(self, start: date, end: date) -> bool:
        return self.effective_start <= start and end <= self.effective_end

    def overlaps(self, start: date, end: date) -> bool:
        return self.effective_start <= end and start <= self.effective_end


def schedules_conflict(
    candidate: TariffSchedule, others: Sequence[TariffSchedule]
) -> bool:
    """Would ``candidate`` overlap a published rule for the same scope?"""
    return any(
        other.distributor == candidate.distributor
        and other.tariff_class == candidate.tariff_class
        and other.overlaps(candidate.effective_start, candidate.effective_end)
        for other in others
    )


class Reason(StrEnum):
    CLASS_NOT_STATED = "class_not_stated"
    CLASS_NOT_SUPPORTED = "class_not_supported"
    DISTRIBUTOR_NOT_SUPPORTED = "distributor_not_supported"
    NO_PUBLISHED_RULE = "no_published_rule"
    RULE_DOES_NOT_COVER_PERIOD = "rule_does_not_cover_period"
    PERIOD_SPANS_RULES = "period_spans_rules"
    KWH_OUTSIDE_PUBLISHED_BANDS = "kwh_outside_published_bands"


@dataclass(frozen=True)
class Abstention:
    reason: Reason


@dataclass(frozen=True)
class EnergyEstimate:
    """Energy and fixed charges, kept apart, from one cited schedule."""

    energy_charge: Decimal
    fixed_charge: Decimal
    schedule: TariffSchedule


def _round(value: Decimal, rounding: Rounding) -> Decimal:
    with localcontext(_ARITHMETIC):
        return value.quantize(
            Decimal(1).scaleb(-rounding.places), rounding=_MODES[rounding.mode]
        )


def _exact(value: Decimal) -> Decimal:
    """Reject a result that the working precision would have had to round."""
    with localcontext(_ARITHMETIC) as context:
        context.traps[Inexact] = True
        return +value


def _energy(kwh: Decimal, schedule: TariffSchedule) -> Decimal | Reason:
    parts: list[Decimal] = []
    all_kwh = next(
        (b for b in schedule.bands if b.charge_type is ChargeType.ENERGY_ALL_KWH), None
    )
    with localcontext(_ARITHMETIC):
        if all_kwh is not None and kwh >= all_kwh.from_kwh:
            parts.append(_exact(kwh * all_kwh.amount))
        else:
            slices = [
                b for b in schedule.bands if b.charge_type is ChargeType.ENERGY_SLICE
            ]
            last_to = slices[-1].to_kwh if slices else Decimal(0)
            if last_to is not None and kwh > last_to:
                return Reason.KWH_OUTSIDE_PUBLISHED_BANDS
            for band in slices:
                upper = kwh if band.to_kwh is None else min(kwh, band.to_kwh)
                width = max(Decimal(0), upper - band.from_kwh)
                parts.append(_exact(width * band.amount))
        if schedule.rounding.scope is RoundingScope.PER_BAND:
            parts = [_round(part, schedule.rounding) for part in parts]
        total = Decimal(0)
        for part in parts:
            total = _exact(total + part)
    return _round(total, schedule.rounding)


def _fixed(kwh: Decimal, schedule: TariffSchedule) -> Decimal | Reason | None:
    ranges = [b for b in schedule.bands if b.charge_type is ChargeType.FIXED_RANGE]
    if not ranges:
        return Decimal(0)
    for band in ranges:
        if kwh >= band.from_kwh and (band.to_kwh is None or kwh <= band.to_kwh):
            return band.amount
    return Reason.KWH_OUTSIDE_PUBLISHED_BANDS


def estimate_energy_charge(
    schedule: TariffSchedule, billed_kwh: Decimal
) -> EnergyEstimate | Abstention:
    """Exact energy and fixed charge for billed kWh under one schedule."""
    if not billed_kwh.is_finite() or billed_kwh < 0:
        return Abstention(Reason.KWH_OUTSIDE_PUBLISHED_BANDS)
    energy = _energy(billed_kwh, schedule)
    if isinstance(energy, Reason):
        return Abstention(energy)
    fixed = _fixed(billed_kwh, schedule)
    if isinstance(fixed, Reason) or fixed is None:
        return Abstention(Reason.KWH_OUTSIDE_PUBLISHED_BANDS)
    return EnergyEstimate(energy_charge=energy, fixed_charge=fixed, schedule=schedule)


def estimate_for_invoice(
    schedules: Sequence[TariffSchedule],
    *,
    distributor: str | None,
    tariff_class: str | None,
    period_start: date,
    period_end: date,
    billed_kwh: Decimal,
) -> EnergyEstimate | Abstention:
    """The first calculator: a stated BTS-1 invoice and one rule covering its period.

    ``schedules`` are the published rules for the invoice's distributor and
    class. The caller never supplies a default class or rate.
    """
    if distributor not in SUPPORTED_DISTRIBUTORS:
        return Abstention(Reason.DISTRIBUTOR_NOT_SUPPORTED)
    if tariff_class is None:
        return Abstention(Reason.CLASS_NOT_STATED)
    if tariff_class != SUPPORTED_CLASS:
        return Abstention(Reason.CLASS_NOT_SUPPORTED)
    scoped = [
        s
        for s in schedules
        if s.distributor.value == distributor and s.tariff_class == tariff_class
    ]
    touching = [s for s in scoped if s.overlaps(period_start, period_end)]
    if not touching:
        return Abstention(Reason.NO_PUBLISHED_RULE)
    covering = [s for s in touching if s.covers(period_start, period_end)]
    if len(covering) == 1 and len(touching) == 1:
        return estimate_energy_charge(covering[0], billed_kwh)
    if len(touching) > 1:
        return Abstention(Reason.PERIOD_SPANS_RULES)
    return Abstention(Reason.RULE_DOES_NOT_COVER_PERIOD)


def schedule_fingerprint(schedule: TariffSchedule) -> dict[str, Any]:
    """Citation fields only; no rates."""
    return {
        "resolution_id": schedule.resolution_id,
        "source_url": schedule.source_url,
        "source_digest": schedule.source_digest,
        "effective_start": schedule.effective_start.isoformat(),
        "effective_end": schedule.effective_end.isoformat(),
    }
