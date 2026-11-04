import tomllib
from pathlib import Path

from energyiq import __version__

PYPROJECT = Path(__file__).parents[2] / "pyproject.toml"


def test_version_matches_pyproject() -> None:
    with PYPROJECT.open("rb") as file:
        data = tomllib.load(file)
    assert __version__ == data["project"]["version"]
