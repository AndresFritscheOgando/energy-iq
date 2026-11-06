"""Synthetic tariff fixtures (spec 0012/0006).

EVERY NUMBER HERE IS INVENTED. These are not SIE rates. The official SIE
resolution has not been transcribed into this repository, so tests prove the
mechanics (bands, boundaries, rounding, abstention), never a real tariff value.
The synthetic "source" is a few bytes, so its digest is real but its content is
not a resolution.
"""

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from energyiq.tariffs.domain import TariffSchedule

SOURCE_BYTES = b"synthetic stand in for an SIE resolution, not a real document"
SOURCE_DIGEST = hashlib.sha256(SOURCE_BYTES).hexdigest()

# Slices: (0,200] at 1.00, (200,300] at 2.00, (300,700] at 3.00; every kWh at
# 4.00 from 701; fixed charge 10.00 up to 100 kWh and 20.00 from 101 kWh.
BANDS: list[dict[str, Any]] = [
    {"charge_type": "energy_slice", "from_kwh": "0", "to_kwh": "200", "amount": "1.00"},
    {
        "charge_type": "energy_slice",
        "from_kwh": "200",
        "to_kwh": "300",
        "amount": "2.00",
    },
    {
        "charge_type": "energy_slice",
        "from_kwh": "300",
        "to_kwh": "700",
        "amount": "3.00",
    },
    {"charge_type": "energy_all_kwh", "from_kwh": "701", "amount": "4.00"},
    {"charge_type": "fixed_range", "from_kwh": "0", "to_kwh": "100", "amount": "10.00"},
    {"charge_type": "fixed_range", "from_kwh": "101", "amount": "20.00"},
]


def schedule_dict(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "distributor": "EDESUR",
        "tariff_class": "BTS-1",
        "effective_start": "2026-10-01",
        "effective_end": "2026-12-31",
        "resolution_id": "SIE-900-2026-TF",
        "source_url": "https://sie.gob.do/synthetic/SIE-900-2026-TF.pdf",
        "source_digest": SOURCE_DIGEST,
        "published_on": "2026-10-02",
        "checked_on": "2026-11-06",
        "checked_by": "Synthetic Reviewer",
        "rounding": {"places": 2, "mode": "half_up", "scope": "total"},
        "bands": deepcopy(BANDS),
    }
    base.update(overrides)
    return base


def schedule(**overrides: Any) -> TariffSchedule:
    return TariffSchedule.model_validate(schedule_dict(**overrides))


def write_manifest(
    directory: Path, schedules: list[dict[str, Any]] | None = None, **top: Any
) -> Path:
    body: dict[str, Any] = {
        "manifest_revision": "synthetic-1",
        "schedules": schedules if schedules is not None else [schedule_dict()],
    }
    body.update(top)
    path = directory / "manifest.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


def write_source(directory: Path, content: bytes = SOURCE_BYTES) -> Path:
    path = directory / "source.bin"
    path.write_bytes(content)
    return path
