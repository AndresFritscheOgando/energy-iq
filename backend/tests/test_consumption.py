from decimal import (
    ROUND_UP,
    Decimal,
    DecimalException,
    Inexact,
    Overflow,
    Rounded,
    Underflow,
    getcontext,
    localcontext,
)
from typing import cast

import pytest

from energyiq.consumption import calculate_consumption


def test_consumption_for_increasing_readings():
    result = calculate_consumption(Decimal("13007.0"), Decimal("13049.0"))

    assert result == Decimal("42.0")
    assert isinstance(result, Decimal)


def test_consumption_for_another_increasing_pair():
    assert calculate_consumption(Decimal("12964.0"), Decimal("12979.0")) == Decimal(
        "15.0"
    )


def test_equal_readings_return_zero():
    assert calculate_consumption(Decimal("15000.0"), Decimal("15000.0")) == Decimal(
        "0.0"
    )


def test_zero_readings_return_zero():
    assert calculate_consumption(Decimal("0.0"), Decimal("0.0")) == Decimal("0.0")


def test_decreasing_readings_raise_value_error():
    with pytest.raises(ValueError):
        calculate_consumption(Decimal("15000.0"), Decimal("14900.0"))


def test_negative_previous_reading_raises_value_error():
    with pytest.raises(ValueError):
        calculate_consumption(Decimal("-5.0"), Decimal("100.0"))


def test_negative_current_reading_raises_value_error():
    with pytest.raises(ValueError):
        calculate_consumption(Decimal("100.0"), Decimal("-5.0"))


def test_fractional_readings_return_exact_consumption():
    assert calculate_consumption(Decimal("0.1"), Decimal("0.3")) == Decimal("0.2")


def test_large_fractional_readings_return_exact_consumption():
    result = calculate_consumption(Decimal("13007.10"), Decimal("13007.30"))

    assert result == Decimal("0.20")


@pytest.mark.parametrize("position", [0, 1], ids=["previous", "current"])
@pytest.mark.parametrize("invalid", [1, 1.5, True, False, "1", None, object()])
def test_consumption_rejects_unsupported_types(position: int, invalid: object):
    readings = [Decimal(0), Decimal(1)]
    readings[position] = cast(Decimal, invalid)
    label = "previous" if position == 0 else "current"

    with pytest.raises(TypeError, match=f"{label} reading must be a Decimal"):
        calculate_consumption(*readings)


@pytest.mark.parametrize("position", [0, 1], ids=["previous", "current"])
@pytest.mark.parametrize("invalid", ["NaN", "sNaN", "Infinity", "-Infinity"])
def test_consumption_rejects_nonfinite_values(position: int, invalid: str):
    readings = [Decimal(0), Decimal(1)]
    readings[position] = Decimal(invalid)
    label = "previous" if position == 0 else "current"

    with localcontext() as context:
        context.clear_flags()
        with pytest.raises(ValueError, match=f"{label} reading.*finite number"):
            calculate_consumption(*readings)
        assert not any(context.flags.values())


@pytest.mark.parametrize(
    ("previous", "current"), [("-0", "0"), ("0", "-0"), ("-0.00", "1.20")]
)
def test_signed_zero_is_a_valid_reading(previous: str, current: str):
    expected = Decimal("1.20") if current == "1.20" else Decimal(0)
    assert calculate_consumption(Decimal(previous), Decimal(current)) == expected


def test_both_types_are_validated_before_any_value_checks():
    with pytest.raises(TypeError, match="current reading"):
        calculate_consumption(Decimal("sNaN"), cast(Decimal, "1"))


def test_both_values_are_checked_for_finiteness_before_comparison():
    with pytest.raises(ValueError, match="current reading.*finite number"):
        calculate_consumption(Decimal(-1), Decimal("sNaN"))


@pytest.mark.parametrize(
    ("previous", "current", "expected"),
    [
        ("0", "1.234", "1.234"),
        ("13007.10", "13007.30", "0.20"),
        ("0", "1e-1000026", "1e-1000026"),
        ("1e1000000", "1e1000000", "0"),
        ("0", "1234567890123456789012345678", "1234567890123456789012345678"),
        ("0", "1.0000000000000000000000000000", "1"),
        ("12345678901234567890123456789", "12345678901234567890123456790", "1"),
    ],
)
@pytest.mark.parametrize("caller_traps_enabled", [False, True])
def test_exact_results_ignore_caller_context_and_preserve_it(
    previous: str, current: str, expected: str, caller_traps_enabled: bool
):
    with localcontext() as context:
        context.prec = 3
        context.rounding = ROUND_UP
        context.Emin = -2
        context.Emax = 2
        context.capitals = 0
        context.clamp = 1
        for signal in context.traps:
            context.traps[signal] = caller_traps_enabled
        context.clear_flags()
        context.flags[Rounded] = True
        before = repr(context)

        result = calculate_consumption(Decimal(previous), Decimal(current))

        assert result == Decimal(expected)
        assert isinstance(result, Decimal)
        assert result.is_finite()
        if expected == "0.20":
            assert str(result) == "0.20"
        assert getcontext() is context
        assert repr(context) == before


@pytest.mark.parametrize("caller_traps_enabled", [False, True])
@pytest.mark.parametrize(
    ("current", "error"),
    [
        ("1.2345678901234567890123456789", Inexact),
        ("1e1000000", Overflow),
        ("1e-1000027", Underflow),
    ],
)
def test_unsupported_arithmetic_raises_without_changing_caller_context(
    current: str, error: type[DecimalException], caller_traps_enabled: bool
):
    with localcontext() as context:
        context.prec = 50
        context.Emin = -2000000
        context.Emax = 2000000
        for signal in context.traps:
            context.traps[signal] = caller_traps_enabled
        context.clear_flags()
        context.flags[Rounded] = True
        before = repr(context)

        with pytest.raises(error):
            calculate_consumption(Decimal(0), Decimal(current))

        assert getcontext() is context
        assert repr(context) == before
        assert calculate_consumption(Decimal("0.1"), Decimal("0.3")) == Decimal("0.2")
        assert repr(context) == before
