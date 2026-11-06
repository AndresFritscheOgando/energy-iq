"""Checked source manifest loading and source digest verification (spec 0012/0006 AC-1)."""

import json
from pathlib import Path

import pytest
from tariffsupport import schedule_dict, write_manifest, write_source

from energyiq.tariffs.manifest import (
    ManifestError,
    file_digest,
    load_manifest,
    verify_sources,
)


def test_valid_manifest_loads(tmp_path: Path) -> None:
    manifest = load_manifest(write_manifest(tmp_path))
    assert manifest.manifest_revision == "synthetic-1"
    assert manifest.schedules[0].resolution_id == "SIE-900-2026-TF"


def test_rate_as_json_number_is_refused_not_rounded(tmp_path: Path) -> None:
    path = write_manifest(tmp_path)
    path.write_text(
        path.read_text(encoding="utf-8").replace('"amount": "1.00"', '"amount": 1.0'),
        encoding="utf-8",
    )
    with pytest.raises(ManifestError, match="decimal string"):
        load_manifest(path)


def test_nan_constant_is_refused(tmp_path: Path) -> None:
    path = write_manifest(tmp_path)
    path.write_text(
        path.read_text(encoding="utf-8").replace('"amount": "1.00"', '"amount": NaN'),
        encoding="utf-8",
    )
    with pytest.raises(ManifestError):
        load_manifest(path)


@pytest.mark.parametrize("text", ["", "not json", "[]", "{}", '{"schedules": []}'])
def test_malformed_manifest_is_refused(tmp_path: Path, text: str) -> None:
    path = tmp_path / "bad.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ManifestError):
        load_manifest(path)


def test_missing_manifest_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ManifestError, match="cannot be read"):
        load_manifest(tmp_path / "absent.json")


def test_unchecked_draft_cannot_load(tmp_path: Path) -> None:
    """A rule with no reviewer or check date stays a draft: it never validates."""
    data = schedule_dict()
    del data["checked_by"]
    del data["checked_on"]
    path = write_manifest(tmp_path, [data])
    with pytest.raises(ManifestError) as caught:
        load_manifest(path)
    assert "checked_by" in str(caught.value)


def test_validation_error_names_fields_not_values(tmp_path: Path) -> None:
    data = schedule_dict(source_digest="not-a-digest-secret-value")
    path = write_manifest(tmp_path, [data])
    with pytest.raises(ManifestError) as caught:
        load_manifest(path)
    assert "source_digest" in str(caught.value)
    assert "secret-value" not in str(caught.value)


def test_two_rules_for_one_scope_and_dates_are_refused(tmp_path: Path) -> None:
    other = schedule_dict(resolution_id="SIE-901-2026-TF")
    path = write_manifest(tmp_path, [schedule_dict(), other])
    with pytest.raises(ManifestError):
        load_manifest(path)


def test_adjacent_rules_for_one_scope_are_allowed(tmp_path: Path) -> None:
    first = schedule_dict(effective_end="2026-10-14", resolution_id="SIE-901-2026-TF")
    second = schedule_dict(effective_start="2026-10-15")
    assert len(load_manifest(write_manifest(tmp_path, [first, second])).schedules) == 2


def test_source_digest_must_match_a_supplied_file(tmp_path: Path) -> None:
    manifest = load_manifest(write_manifest(tmp_path))
    verify_sources(manifest, [write_source(tmp_path)])
    other = tmp_path / "other.bin"
    other.write_bytes(b"a different document")
    with pytest.raises(ManifestError, match="no source file matches"):
        verify_sources(manifest, [other])


def test_a_source_file_is_required(tmp_path: Path) -> None:
    manifest = load_manifest(write_manifest(tmp_path))
    with pytest.raises(ManifestError, match="source file is required"):
        verify_sources(manifest, [])


def test_file_digest_is_sha256(tmp_path: Path) -> None:
    path = tmp_path / "a.bin"
    path.write_bytes(b"abc")
    assert (
        file_digest(path)
        == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )


def test_manifest_json_round_trip_keeps_decimal_strings(tmp_path: Path) -> None:
    path = write_manifest(tmp_path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert all(isinstance(b["amount"], str) for b in raw["schedules"][0]["bands"])
