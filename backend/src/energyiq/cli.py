"""Local cumulative-reading calculator; no persistence or external services."""

import sys
from decimal import Decimal, DecimalException, InvalidOperation

from energyiq.consumption import calculate_consumption


def _read_reading(label: str) -> Decimal:
    raw = input(f"{label.capitalize()} cumulative reading (kWh): ").strip()
    try:
        reading = Decimal(raw)
    except InvalidOperation:
        raise ValueError(f"{label} reading must be a decimal number") from None

    if not reading.is_finite():
        raise ValueError(f"{label} reading must be a finite number")

    return reading


def main() -> int:
    """Prompt for two readings; return 0, 2 for input errors, or 130 on cancel."""
    try:
        previous = _read_reading("previous")
        current = _read_reading("current")
        consumption = calculate_consumption(previous, current)
    except ValueError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2
    except DecimalException:
        print(
            "Error: readings exceed supported decimal arithmetic limits",
            file=sys.stderr,
        )
        return 2
    except EOFError:
        print("Error: two cumulative readings are required", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return 130

    print(f"Consumption: {consumption} kWh")
    return 0
