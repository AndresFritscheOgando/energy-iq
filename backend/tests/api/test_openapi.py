"""OpenAPI contract and the framework free domain boundary: AC-12.

Regenerate the snapshot after an intended change with
``ENERGYIQ_UPDATE_SNAPSHOTS=1 uv run pytest backend/tests/api/test_openapi.py``.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI

SNAPSHOT = Path(__file__).parents[1] / "snapshots" / "openapi.json"
SRC = Path(__file__).parents[2] / "src"
SUMMARY = "/api/v1/consumption/summary"


def _dump(schema: dict[str, Any]) -> str:
    return json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def test_openapi_matches_snapshot(app: FastAPI) -> None:
    current = _dump(app.openapi())
    if os.environ.get("ENERGYIQ_UPDATE_SNAPSHOTS") == "1":
        SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT.write_text(current, encoding="utf-8", newline="\n")

    assert current == SNAPSHOT.read_text(encoding="utf-8")


def test_error_responses_are_problem_json_only(app: FastAPI) -> None:
    responses = app.openapi()["paths"][SUMMARY]["post"]["responses"]

    errors = {"400", "401", "403", "413", "415", "422", "500", "503"}
    assert set(responses) == {"200", *errors}
    for status in errors:
        content = responses[status]["content"]
        assert set(content) == {"application/problem+json"}
        assert content["application/problem+json"]["schema"] == {
            "$ref": "#/components/schemas/ConsumptionProblem"
        }
    assert set(responses["200"]["content"]) == {"application/json"}


def test_no_default_validation_schemas(app: FastAPI) -> None:
    schemas = app.openapi()["components"]["schemas"]

    assert "HTTPValidationError" not in schemas
    assert "ValidationError" not in schemas


def test_decimal_and_time_outputs_are_strings(app: FastAPI) -> None:
    schemas = app.openapi()["components"]["schemas"]
    response = schemas["ConsumptionSummaryResponse"]["properties"]
    interval = schemas["IntervalOut"]["properties"]

    for name in ("measured_kwh", "covered", "uncovered", "coverage_ratio"):
        assert response[name]["type"] == "string"
    assert {"type": "string"} in response["average_kwh_per_day"]["anyOf"]
    for name in ("start", "end", "duration"):
        assert interval[name]["type"] == "string"
    assert {"type": "string"} in interval["consumption_kwh"]["anyOf"]
    assert {"type": "string"} in interval["kwh_per_day"]["anyOf"]


def test_readings_domain_imports_no_framework() -> None:
    code = (
        "import sys, energyiq.readings; "
        "print(','.join(m for m in ('fastapi', 'starlette', 'pydantic', 'pydantic_core', "
        "'sqlalchemy', 'psycopg', 'alembic') "
        "if m in sys.modules))"
    )

    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, "PYTHONPATH": str(SRC)},
    )

    assert result.stdout.strip() == ""
