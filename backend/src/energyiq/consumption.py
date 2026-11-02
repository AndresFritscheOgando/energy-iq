from decimal import Decimal


def calculate_consumption(
    previous_reading: Decimal, current_reading: Decimal
) -> Decimal:
    """Return consumption in kWh between two cumulative readings.

    Raise ValueError if either reading is negative or the readings decrease.
    """
    if previous_reading < 0:
        raise ValueError("previous reading cannot be less than 0")

    if current_reading < 0:
        raise ValueError("current reading cannot be less than 0")

    if current_reading < previous_reading:
        raise ValueError("current reading cannot be less than previous reading")

    return current_reading - previous_reading
