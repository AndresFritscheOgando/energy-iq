"""The checked source manifest (spec 0012/0006 AC-1).

A manifest is a version controlled JSON file that a human reviewer wrote after
reading the official SIE resolution. It names the reviewer, resolution, source
digest, and the exact rule values. Amounts are decimal strings, never JSON
numbers, so no binary float can hide inside a rate. Nothing here fetches a
document or generates a value.
"""

import hashlib
import json
from pathlib import Path
from typing import Annotated, Any, NoReturn

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from pydantic_core import PydanticCustomError

from energyiq.tariffs.domain import TariffSchedule

MAX_MANIFEST_BYTES = 256 * 1024
MAX_SOURCE_BYTES = 64 * 1024 * 1024
_CHUNK = 1024 * 1024


class ManifestError(ValueError):
    """The manifest or its source cannot be trusted; the message names why."""


class TariffManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    manifest_revision: Annotated[str, Field(pattern=r"^[A-Za-z0-9._-]{1,64}$")]
    schedules: Annotated[tuple[TariffSchedule, ...], Field(min_length=1, max_length=20)]

    @model_validator(mode="after")
    def no_overlap(self) -> "TariffManifest":
        for index, schedule in enumerate(self.schedules):
            for other in self.schedules[index + 1 :]:
                same_scope = (
                    schedule.distributor == other.distributor
                    and schedule.tariff_class == other.tariff_class
                )
                if same_scope and schedule.overlaps(
                    other.effective_start, other.effective_end
                ):
                    raise PydanticCustomError(
                        "manifest_overlap",
                        "Two rules in one manifest cover the same scope and dates.",
                    )
        return self


def _no_float(value: str) -> NoReturn:
    raise ManifestError(f"use a decimal string, not the number {value}")


def load_manifest(path: Path) -> TariffManifest:
    """Parse and validate a manifest; raises :class:`ManifestError`."""
    try:
        size = path.stat().st_size
        if size > MAX_MANIFEST_BYTES:
            raise ManifestError("manifest is too large")
        raw: Any = json.loads(
            path.read_text(encoding="utf-8"),
            parse_float=_no_float,
            parse_constant=_no_float,
        )
    except OSError:
        raise ManifestError("manifest cannot be read") from None
    except json.JSONDecodeError:
        raise ManifestError("manifest is not valid JSON") from None
    try:
        return TariffManifest.model_validate(raw)
    except ValidationError as exc:
        places = sorted({".".join(map(str, error["loc"])) for error in exc.errors()})
        raise ManifestError(f"manifest is invalid at: {', '.join(places)}") from None


def file_digest(path: Path) -> str:
    """SHA-256 of a source document, read in chunks with a size cap."""
    digest = hashlib.sha256()
    total = 0
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(_CHUNK):
                total += len(chunk)
                if total > MAX_SOURCE_BYTES:
                    raise ManifestError("source file is too large")
                digest.update(chunk)
    except OSError:
        raise ManifestError("source file cannot be read") from None
    return digest.hexdigest()


def verify_sources(manifest: TariffManifest, sources: list[Path]) -> None:
    """Every schedule's digest must match a supplied source file."""
    if not sources:
        raise ManifestError("a source file is required to verify the digest")
    known = {file_digest(path) for path in sources}
    for schedule in manifest.schedules:
        if schedule.source_digest not in known:
            raise ManifestError(
                f"no source file matches the digest for {schedule.resolution_id}"
                f" {schedule.distributor.value}"
            )
