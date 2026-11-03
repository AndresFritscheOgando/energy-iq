import os
import subprocess
import sys
from pathlib import Path

import pytest

from energyiq.cli import main


@pytest.mark.parametrize(
    ("previous", "current", "expected"),
    [
        ("13007", "13049", "42"),
        ("12964", "12979", "15"),
        ("15000", "15000", "0"),
        ("0", "0", "0"),
        ("0.1", "0.3", "0.2"),
        ("13007.10", "13007.30", "0.20"),
        (" 100.1 ", " 105.3 ", "5.2"),
    ],
)
def test_cli_prints_consumption_for_valid_readings(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    previous: str,
    current: str,
    expected: str,
):
    readings = iter([previous, current])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(readings))

    assert main() == 0

    captured = capsys.readouterr()
    assert captured.out == f"Consumption: {expected} kWh\n"
    assert captured.err == ""


@pytest.mark.parametrize("position", [0, 1], ids=["previous", "current"])
@pytest.mark.parametrize(
    ("invalid", "reason"),
    [
        ("", "decimal number"),
        ("   ", "decimal number"),
        ("abc", "decimal number"),
        ("1,234.5", "decimal number"),
        ("NaN", "finite number"),
        ("sNaN", "finite number"),
        ("Infinity", "finite number"),
        ("-Infinity", "finite number"),
    ],
)
def test_cli_rejects_malformed_or_non_finite_readings(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    position: int,
    invalid: str,
    reason: str,
):
    values = ["100.1", "142.2"]
    values[position] = invalid
    readings = iter(values)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(readings))

    assert main() == 2

    captured = capsys.readouterr()
    label = "previous" if position == 0 else "current"
    assert captured.err == f"Error: {label} reading must be a {reason}\n"
    assert captured.out == ""


@pytest.mark.parametrize(
    ("previous", "current", "message"),
    [
        ("-5", "100", "previous reading cannot be less than 0"),
        ("100", "-5", "current reading cannot be less than 0"),
        ("15000", "14900", "current reading cannot be less than previous reading"),
        ("0", "1e1000000", "readings exceed supported decimal arithmetic limits"),
    ],
)
def test_cli_reports_domain_and_arithmetic_errors(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    previous: str,
    current: str,
    message: str,
):
    readings = iter([previous, current])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(readings))

    assert main() == 2

    captured = capsys.readouterr()
    assert captured.err == f"Error: {message}\n"
    assert captured.out == ""


@pytest.mark.parametrize("after_first_reading", [False, True])
@pytest.mark.parametrize(
    ("interruption", "status", "message"),
    [
        (EOFError, 2, "Error: two cumulative readings are required\n"),
        (KeyboardInterrupt, 130, "\nCancelled.\n"),
    ],
)
def test_cli_handles_incomplete_input_and_cancellation(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    after_first_reading: bool,
    interruption: type[EOFError] | type[KeyboardInterrupt],
    status: int,
    message: str,
):
    values = iter(["100.1"] if after_first_reading else [])

    def read_input(prompt: str) -> str:
        try:
            return next(values)
        except StopIteration:
            raise interruption from None

    monkeypatch.setattr("builtins.input", read_input)

    assert main() == status

    captured = capsys.readouterr()
    assert captured.err == message
    assert captured.out == ""


@pytest.mark.parametrize(
    ("user_input", "status", "consumption", "error"),
    [
        ("13007\n13049\n", 0, "42", ""),
        ("0.1\n0.3\n", 0, "0.2", ""),
        ("13007.10\n13007.30\n", 0, "0.20", ""),
        ("1e2\n1.42e2\n", 0, "42", ""),
        (
            "0\n1.2345678901234567890123456789\n",
            2,
            "",
            "readings exceed supported decimal arithmetic limits",
        ),
        (
            "0\n1e1000000\n",
            2,
            "",
            "readings exceed supported decimal arithmetic limits",
        ),
        (
            "0\n1e-1000027\n",
            2,
            "",
            "readings exceed supported decimal arithmetic limits",
        ),
        ("abc\n", 2, "", "previous reading must be a decimal number"),
        ("100\nNaN\n", 2, "", "current reading must be a finite number"),
        ("100\n99\n", 2, "", "current reading cannot be less than previous reading"),
        ("100\n", 2, "", "two cumulative readings are required"),
    ],
)
def test_module_entry_point_prompts_and_returns_process_status(
    user_input: str, status: int, consumption: str, error: str
):
    root = Path(__file__).resolve().parents[2]
    environment = {**os.environ, "PYTHONPATH": str(root / "backend" / "src")}

    result = subprocess.run(
        [sys.executable, "-m", "energyiq"],
        input=user_input,
        capture_output=True,
        text=True,
        env=environment,
        cwd=root,
        timeout=10,
        check=False,
    )

    assert result.returncode == status
    assert result.stdout.startswith("Previous cumulative reading (kWh): ")
    if consumption:
        assert "Current cumulative reading (kWh): " in result.stdout
        assert result.stdout.endswith(f"Consumption: {consumption} kWh\n")
        assert result.stderr == ""
    else:
        assert "Consumption:" not in result.stdout
        assert result.stderr == f"Error: {error}\n"


def test_importing_calculator_and_entry_point_has_no_side_effects():
    root = Path(__file__).resolve().parents[2]
    environment = {**os.environ, "PYTHONPATH": str(root / "backend" / "src")}

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import energyiq.consumption; import energyiq.cli; import energyiq.__main__",
        ],
        input="",
        capture_output=True,
        text=True,
        env=environment,
        cwd=root,
        timeout=10,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""
