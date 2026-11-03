from decimal import (
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    DivisionByZero,
    Inexact,
    InvalidOperation,
    Overflow,
    Underflow,
    localcontext,
)


def exact_kwh_context() -> Context:
    """Return a fresh Decimal context for exact kWh arithmetic.

    Precision 28 with every lossy signal trapped, so a result that cannot be
    held exactly raises a DecimalException instead of rounding. The policy is
    fixed independently of the caller's context and of decimal.DefaultContext.
    """
    return Context(
        prec=28,
        rounding=ROUND_HALF_EVEN,
        Emin=-999999,
        Emax=999999,
        capitals=1,
        clamp=0,
        flags=[],
        traps=[InvalidOperation, DivisionByZero, Overflow, Underflow, Inexact],
    )


def calculate_consumption(
    previous_reading: Decimal, current_reading: Decimal
) -> Decimal:
    """Return an exact Decimal difference between cumulative kWh readings.

    Raise TypeError for non Decimal inputs and ValueError for nonfinite,
    negative, or decreasing readings. Unsupported exact arithmetic raises
    a DecimalException subtype. Leave the caller's Decimal context untouched.
    """
    for label, reading in (
        ("previous", previous_reading),
        ("current", current_reading),
    ):
        if not isinstance(reading, Decimal):
            raise TypeError(f"{label} reading must be a Decimal")

    for label, reading in (
        ("previous", previous_reading),
        ("current", current_reading),
    ):
        if not reading.is_finite():
            raise ValueError(f"{label} reading must be a finite number")

    if previous_reading < 0:
        raise ValueError("previous reading cannot be less than 0")

    if current_reading < 0:
        raise ValueError("current reading cannot be less than 0")

    if current_reading < previous_reading:
        raise ValueError("current reading cannot be less than previous reading")

    with localcontext(exact_kwh_context()):
        return current_reading - previous_reading
