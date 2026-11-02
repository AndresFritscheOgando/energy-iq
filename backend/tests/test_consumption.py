from decimal import Decimal

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
