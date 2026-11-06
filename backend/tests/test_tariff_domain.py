"""Tariff validation and the BTS-1 calculator, with synthetic values only (spec 0012/0006)."""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError
from tariffsupport import BANDS, schedule

from energyiq.tariffs.domain import (
    Abstention,
    EnergyEstimate,
    Reason,
    estimate_energy_charge,
    estimate_for_invoice,
    schedules_conflict,
)

D = Decimal


def _estimate(kwh: str, **overrides: Any) -> EnergyEstimate:
    result = estimate_energy_charge(schedule(**overrides), D(kwh))
    assert isinstance(result, EnergyEstimate), result
    return result


@pytest.mark.parametrize(
    ("kwh", "energy", "fixed"),
    [
        ("0", "0.00", "10.00"),  # zero use is a true zero, with its fixed charge
        ("100", "100.00", "10.00"),
        ("101", "101.00", "20.00"),
        ("200", "200.00", "20.00"),  # exact top of the first slice
        ("200.5", "201.00", "20.00"),
        ("201", "202.00", "20.00"),
        ("300", "400.00", "20.00"),  # 200*1 + 100*2
        ("301", "403.00", "20.00"),
        ("700", "1600.00", "20.00"),  # 200 + 200 + 400*3
        ("701", "2804.00", "20.00"),  # all kWh at 4.00 from 701
        ("1000", "4000.00", "20.00"),
    ],
)
def test_exact_boundaries(kwh: str, energy: str, fixed: str) -> None:
    result = _estimate(kwh)
    assert result.energy_charge == D(energy)
    assert result.fixed_charge == D(fixed)


@pytest.mark.parametrize("kwh", ["700.000001", "700.5", "700.999999"])
def test_kwh_between_published_ranges_is_not_priced(kwh: str) -> None:
    result = estimate_energy_charge(schedule(), D(kwh))
    assert result == Abstention(Reason.KWH_OUTSIDE_PUBLISHED_BANDS)


def test_fixed_charge_gap_is_not_priced() -> None:
    result = estimate_energy_charge(schedule(), D("100.5"))
    assert result == Abstention(Reason.KWH_OUTSIDE_PUBLISHED_BANDS)


@pytest.mark.parametrize("kwh", ["-1", "NaN", "Infinity"])
def test_invalid_kwh_abstains(kwh: str) -> None:
    assert isinstance(estimate_energy_charge(schedule(), D(kwh)), Abstention)


@pytest.mark.parametrize(
    ("mode", "expected"),
    [("half_up", "0.13"), ("half_even", "0.12"), ("up", "0.13"), ("down", "0.12")],
)
def test_rounding_modes_are_source_specified(mode: str, expected: str) -> None:
    bands = [
        {
            "charge_type": "energy_slice",
            "from_kwh": "0",
            "to_kwh": "10",
            "amount": "0.125",
        }
    ]
    result = _estimate(
        "1", bands=bands, rounding={"places": 2, "mode": mode, "scope": "total"}
    )
    assert result.energy_charge == D(expected)


def test_rounding_scope_total_versus_per_band() -> None:
    bands = [
        {
            "charge_type": "energy_slice",
            "from_kwh": "0",
            "to_kwh": "1",
            "amount": "0.125",
        },
        {
            "charge_type": "energy_slice",
            "from_kwh": "1",
            "to_kwh": "2",
            "amount": "0.125",
        },
    ]
    total = _estimate(
        "2", bands=bands, rounding={"places": 2, "mode": "half_up", "scope": "total"}
    )
    per_band = _estimate(
        "2", bands=bands, rounding={"places": 2, "mode": "half_up", "scope": "per_band"}
    )
    assert total.energy_charge == D("0.25")
    assert per_band.energy_charge == D("0.26")


def test_result_is_exact_decimal_never_float() -> None:
    result = _estimate("250.123456")
    assert isinstance(result.energy_charge, Decimal)
    assert result.energy_charge == D("300.25")  # 200 + 50.123456*2 = 300.246912


def test_open_ended_last_slice_has_no_upper_gap() -> None:
    bands = [
        {"charge_type": "energy_slice", "from_kwh": "0", "to_kwh": "10", "amount": "1"},
        {"charge_type": "energy_slice", "from_kwh": "10", "amount": "2"},
    ]
    assert _estimate("15", bands=bands).energy_charge == D("20.00")


def test_schedule_without_fixed_range_has_zero_fixed_charge() -> None:
    bands = [b for b in BANDS if b["charge_type"] != "fixed_range"]
    assert _estimate("50", bands=bands).fixed_charge == D(0)


# Validation ---------------------------------------------------------------


@pytest.mark.parametrize(
    "patch",
    [
        {"effective_end": "2026-09-30"},
        {"published_on": "2026-11-07"},  # checked before published
        {"source_digest": "ABC"},
        {"source_digest": "A" * 64},
        {"source_url": "http://sie.gob.do/x.pdf"},
        {"source_url": "https://example.com/x.pdf"},
        {"source_url": "https://sie.gob.do.evil.test/x.pdf"},
        {"source_url": "https://user:pw@sie.gob.do/x.pdf"},
        {"resolution_id": "rate-2026"},
        {"tariff_class": "BTS-2"},
        {"distributor": "OTHER"},
        {"checked_by": "a@b.test"},
        {"checked_by": ""},
        {"bands": []},
        {"extra_field": "x"},
        {"rounding": {"places": 7, "mode": "half_up", "scope": "total"}},
        {"rounding": {"places": 2, "mode": "banker", "scope": "total"}},
    ],
)
def test_invalid_schedule_is_rejected(patch: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        schedule(**patch)


def _slice(from_kwh: str, to_kwh: str | None, amount: str = "1") -> dict[str, Any]:
    band: dict[str, Any] = {
        "charge_type": "energy_slice",
        "from_kwh": from_kwh,
        "amount": amount,
    }
    if to_kwh is not None:
        band["to_kwh"] = to_kwh
    return band


@pytest.mark.parametrize(
    "bands",
    [
        [_slice("0", "100"), _slice("50", "200")],  # overlap
        [_slice("0", "100"), _slice("101", "200")],  # slices must be contiguous
        [_slice("5", "100")],  # first slice starts above zero
        [_slice("0", "100"), _slice("100", "100")],  # empty slice
        [_slice("0", None), _slice("0", "100")],  # open slice not last
        [_slice("0", "100", "-1")],  # negative rate
        [_slice("0", "100", "1.0000001")],  # more places than the source scale
        [
            _slice("0", "100"),
            {"charge_type": "energy_all_kwh", "from_kwh": "50", "amount": "1"},
        ],  # all kWh band inside the slices
        [
            _slice("0", "100"),
            {"charge_type": "energy_all_kwh", "from_kwh": "101", "amount": "1"},
            _slice("100", "200"),
        ],  # all kWh band not last
        [
            {
                "charge_type": "fixed_range",
                "from_kwh": "0",
                "to_kwh": "10",
                "amount": "1",
            }
        ],  # no energy band
        [
            _slice("0", "100"),
            {"charge_type": "fixed_range", "from_kwh": "5", "amount": "1"},
        ],  # fixed ranges start at zero
        [
            _slice("0", "100"),
            {
                "charge_type": "fixed_range",
                "from_kwh": "0",
                "to_kwh": "10",
                "amount": "1",
            },
            {"charge_type": "fixed_range", "from_kwh": "10", "amount": "2"},
        ],  # fixed ranges overlap
    ],
)
def test_invalid_bands_are_rejected(bands: list[dict[str, Any]]) -> None:
    with pytest.raises(ValidationError):
        schedule(bands=bands)


@pytest.mark.parametrize("value", [1.5, 2, None, True])
def test_amounts_must_be_decimal_strings(value: Any) -> None:
    bands = [_slice("0", "100")]
    bands[0]["amount"] = value
    with pytest.raises(ValidationError):
        schedule(bands=bands)


# Applicability ---------------------------------------------------------------


def _invoice(
    schedules: list[Any],
    *,
    distributor: str | None = "EDESUR",
    tariff_class: str | None = "BTS-1",
    start: date = date(2026, 10, 1),
    end: date = date(2026, 10, 31),
    kwh: str = "250",
) -> EnergyEstimate | Abstention:
    return estimate_for_invoice(
        schedules,
        distributor=distributor,
        tariff_class=tariff_class,
        period_start=start,
        period_end=end,
        billed_kwh=D(kwh),
    )


def test_covered_period_is_estimated_with_citation() -> None:
    result = _invoice([schedule()])
    assert isinstance(result, EnergyEstimate)
    assert result.schedule.resolution_id == "SIE-900-2026-TF"
    assert result.energy_charge == D("300.00")


def test_period_may_use_the_first_and_last_effective_day() -> None:
    result = _invoice([schedule()], start=date(2026, 10, 1), end=date(2026, 12, 31))
    assert isinstance(result, EnergyEstimate)


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"tariff_class": None}, Reason.CLASS_NOT_STATED),
        ({"tariff_class": "BTS-2"}, Reason.CLASS_NOT_SUPPORTED),
        ({"tariff_class": "bts-1"}, Reason.CLASS_NOT_SUPPORTED),
        ({"distributor": "OTHER"}, Reason.DISTRIBUTOR_NOT_SUPPORTED),
        ({"distributor": None}, Reason.DISTRIBUTOR_NOT_SUPPORTED),
        ({"distributor": "EDENORTE"}, Reason.NO_PUBLISHED_RULE),  # wrong distributor
        (
            {"start": date(2026, 9, 15), "end": date(2026, 10, 14)},
            Reason.RULE_DOES_NOT_COVER_PERIOD,
        ),
        (
            {"start": date(2026, 12, 15), "end": date(2027, 1, 14)},
            Reason.RULE_DOES_NOT_COVER_PERIOD,
        ),
        (
            {"start": date(2027, 2, 1), "end": date(2027, 2, 28)},
            Reason.NO_PUBLISHED_RULE,
        ),
    ],
)
def test_calculator_abstains_with_a_reason(kwargs: Any, reason: Reason) -> None:
    assert _invoice([schedule()], **kwargs) == Abstention(reason)


def test_no_schedule_returns_no_estimate() -> None:
    assert _invoice([]) == Abstention(Reason.NO_PUBLISHED_RULE)


def test_period_split_across_two_rules_abstains() -> None:
    first = schedule(effective_end="2026-10-14", resolution_id="SIE-901-2026-TF")
    second = schedule(effective_start="2026-10-15", resolution_id="SIE-902-2026-TF")
    result = _invoice([first, second])
    assert result == Abstention(Reason.PERIOD_SPANS_RULES)


def test_a_later_resolution_applies_only_inside_its_own_dates() -> None:
    first = schedule(effective_end="2026-10-14", resolution_id="SIE-901-2026-TF")
    second = schedule(effective_start="2026-10-15", resolution_id="SIE-902-2026-TF")
    result = _invoice([first, second], start=date(2026, 10, 15), end=date(2026, 10, 31))
    assert isinstance(result, EnergyEstimate)
    assert result.schedule.resolution_id == "SIE-902-2026-TF"


def test_schedules_conflict_only_for_the_same_scope_and_dates() -> None:
    base = schedule()
    assert schedules_conflict(schedule(resolution_id="SIE-901-2026-TF"), [base])
    assert not schedules_conflict(
        schedule(resolution_id="SIE-901-2026-TF", distributor="EDENORTE"), [base]
    )
    assert not schedules_conflict(
        schedule(
            resolution_id="SIE-901-2026-TF",
            effective_start="2027-01-01",
            effective_end="2027-03-31",
        ),
        [base],
    )
