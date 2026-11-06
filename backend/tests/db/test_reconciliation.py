"""Reconciliation route with synthetic data only (spec 0012/0006 AC-3 to AC-5).

Rates come from ``tariffsupport`` and are invented. Readings sit exactly on the
bill window edges: for ``America/Santo_Domingo`` (UTC-4) the window for
2026-10-01..2026-10-31 is 2026-10-01T04:00Z to 2026-11-01T04:00Z.
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from dbsupport import CSRF, PASSWORD
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from tariffsupport import schedule_dict, write_manifest

from energyiq.main import create_app
from energyiq.platform.settings import Settings
from energyiq.tariffs import publish
from energyiq.tariffs.manifest import load_manifest

pytestmark = pytest.mark.db_commit

V1 = "/api/v1"
START = "2026-10-01T04:00:00Z"
END = "2026-11-01T04:00:00Z"
PERIOD = {"period_start": "2026-10-01", "period_end": "2026-10-31"}


@pytest.fixture
def app(committed_db: Engine, db_settings: Settings) -> FastAPI:
    return create_app(db_settings)


def _created(response: Any) -> str:
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _owner(app: FastAPI, label: str = "Owner") -> tuple[TestClient, str]:
    client = TestClient(app, headers=CSRF)
    _created(
        client.post(
            f"{V1}/auth/register",
            json={
                "email": f"{label}-{uuid4().hex[:8]}@example.test",
                "password": PASSWORD,
            },
        )
    )
    home = _created(client.post(f"{V1}/properties", json={"nickname": label}))
    meter = _created(
        client.post(
            f"{V1}/properties/{home}/meters",
            json={"distributor": "EDESUR", "label": "Main"},
        )
    )
    return client, meter


def _read(client: TestClient, meter: str, at: str, kwh: str) -> None:
    _created(
        client.post(
            f"{V1}/meters/{meter}/readings",
            json={"recorded_at": at, "cumulative_kwh": kwh},
        )
    )


def _invoice(
    client: TestClient, meter: str, *, confirm: bool = True, **fields: Any
) -> str:
    body: dict[str, Any] = {
        "distributor": "EDESUR",
        **PERIOD,
        "billed_kwh": "250",
        "total_dop": "999.00",
        **fields,
    }
    body = {k: v for k, v in body.items() if v is not None}
    invoice = client.post(f"{V1}/meters/{meter}/invoices", json=body)
    invoice_id = _created(invoice)
    if confirm:
        draft = invoice.json()["revisions"][0]["id"]
        done = client.post(
            f"{V1}/invoices/{invoice_id}/confirm",
            json={"draft_revision_id": draft, "expected_current_revision_id": None},
        )
        assert done.status_code == 200, done.text
    return invoice_id


def _publish(engine: Engine, directory: Path, *schedules: dict[str, Any]) -> None:
    manifest = load_manifest(
        write_manifest(directory, list(schedules) or [schedule_dict()])
    )
    code, _ = publish.apply_manifest(
        engine, manifest, publish=True, now=datetime(2026, 11, 6, tzinfo=UTC)
    )
    assert code == 0


def _get(client: TestClient, meter: str, invoice: str) -> Any:
    return client.get(
        f"{V1}/meters/{meter}/reconciliation", params={"invoice_id": invoice}
    )


@pytest.fixture
def covered(app: FastAPI) -> tuple[TestClient, str]:
    client, meter = _owner(app)
    _read(client, meter, START, "1000")
    _read(client, meter, END, "1250")
    return client, meter


def test_full_coverage_match_and_estimate(
    covered: tuple[TestClient, str], migrator_engine: Engine, tmp_path: Path
) -> None:
    client, meter = covered
    _publish(migrator_engine, tmp_path)
    invoice = _invoice(client, meter, tariff_class="BTS-1", energy_charge_dop="123.45")
    response = _get(client, meter, invoice)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["window"] == {
        "local_start": "2026-10-01",
        "local_end": "2026-10-31",
        "timezone": "America/Santo_Domingo",
        "utc_start": START,
        "utc_end": END,
    }
    assert body["coverage"]["complete"] is True and body["coverage"]["gaps"] == []
    assert body["comparison"] == {
        "status": "compared",
        "billed_kwh": "250.000000",
        "measured_kwh": "250.000000",
        "difference_kwh": "0.000000",
        "conclusion": "match",
        "reasons": [],
    }
    # 200 kWh at 1.00 plus 50 kWh at 2.00 (synthetic), fixed charge 20.00 from 101 kWh
    assert body["estimate"]["status"] == "estimated"
    assert body["estimate"]["energy_charge_dop"] == "300.00"
    assert body["estimate"]["fixed_charge_dop"] == "20.00"
    assert body["estimate"]["rule"]["resolution_id"] == "SIE-900-2026-TF"
    assert body["estimate"]["rule"]["effective_end"] == "2026-12-31"
    # invoice total, stated energy charge, and estimate stay separate
    assert body["invoice"]["total_dop"] == "999.00"
    assert body["invoice"]["stated_energy_charge_dop"] == "123.45"
    assert body["invoice"]["not_itemized"] == [
        "taxes",
        "fees",
        "arrears",
        "other_charges",
    ]


def test_mismatch_reports_the_exact_difference(
    covered: tuple[TestClient, str],
) -> None:
    client, meter = covered
    invoice = _invoice(client, meter, billed_kwh="260.5")
    comparison = _get(client, meter, invoice).json()["comparison"]
    assert comparison["conclusion"] == "mismatch"
    assert comparison["difference_kwh"] == "10.500000"
    assert comparison["measured_kwh"] == "250.000000"


def test_true_zero_with_full_coverage(app: FastAPI) -> None:
    client, meter = _owner(app)
    _read(client, meter, START, "500")
    _read(client, meter, END, "500")
    invoice = _invoice(client, meter, billed_kwh="0")
    comparison = _get(client, meter, invoice).json()["comparison"]
    assert comparison["measured_kwh"] == "0.000000"
    assert comparison["conclusion"] == "match"


def test_partial_coverage_gives_no_numeric_conclusion(app: FastAPI) -> None:
    client, meter = _owner(app)
    _read(client, meter, "2026-10-03T04:00:00Z", "1000")
    _read(client, meter, END, "1250")
    invoice = _invoice(client, meter)
    body = _get(client, meter, invoice).json()
    assert body["coverage"]["complete"] is False
    assert [gap["reason"] for gap in body["coverage"]["gaps"]] == [
        "before_first_reading"
    ]
    assert body["comparison"]["status"] == "not_comparable"
    assert body["comparison"]["measured_kwh"] is None  # partial use is withheld
    assert body["comparison"]["difference_kwh"] is None
    assert body["comparison"]["conclusion"] is None
    assert body["comparison"]["reasons"] == ["coverage_incomplete"]


def test_no_readings_is_not_zero(app: FastAPI) -> None:
    client, meter = _owner(app)
    invoice = _invoice(client, meter, billed_kwh="0")
    comparison = _get(client, meter, invoice).json()["comparison"]
    assert comparison["measured_kwh"] is None
    assert comparison["difference_kwh"] is None and comparison["conclusion"] is None


def test_readings_that_straddle_the_bill_edges_are_not_prorated(app: FastAPI) -> None:
    client, meter = _owner(app)
    _read(client, meter, "2026-09-30T12:00:00Z", "900")
    _read(client, meter, "2026-11-01T12:00:00Z", "1300")
    invoice = _invoice(client, meter, billed_kwh="400")
    comparison = _get(client, meter, invoice).json()["comparison"]
    assert comparison["conclusion"] is None and comparison["measured_kwh"] is None


def test_bill_window_uses_the_property_time_zone(app: FastAPI) -> None:
    client, meter = _owner(app)
    _read(client, meter, "2026-10-05T00:00:00Z", "10")  # local midnight in UTC
    _read(client, meter, "2026-10-06T00:00:00Z", "20")
    invoice = _invoice(
        client,
        meter,
        period_start="2026-10-05",
        period_end="2026-10-05",
        billed_kwh="10",
    )
    # Santo Domingo midnight is 04:00Z, so UTC midnight readings do not align.
    body = _get(client, meter, invoice).json()
    assert body["window"]["utc_start"] == "2026-10-05T04:00:00Z"
    assert body["comparison"]["conclusion"] is None


@pytest.mark.parametrize(
    ("fields", "reason"),
    [
        ({"tariff_class": None}, "class_not_stated"),
        ({"tariff_class": "BTS-2"}, "class_not_supported"),
        ({"tariff_class": "BTS-1"}, "no_published_rule"),
    ],
)
def test_estimate_abstains_with_a_reason_when_nothing_is_published(
    covered: tuple[TestClient, str], fields: dict[str, Any], reason: str
) -> None:
    client, meter = covered
    estimate = _get(client, meter, _invoice(client, meter, **fields)).json()["estimate"]
    assert estimate == {
        "status": "abstained",
        "reason": reason,
        "energy_charge_dop": None,
        "fixed_charge_dop": None,
        "rule": None,
    }


def test_estimate_abstains_when_the_rule_covers_only_part_of_the_period(
    covered: tuple[TestClient, str], migrator_engine: Engine, tmp_path: Path
) -> None:
    client, meter = covered
    _publish(migrator_engine, tmp_path, schedule_dict(effective_start="2026-10-15"))
    estimate = _get(
        client, meter, _invoice(client, meter, tariff_class="BTS-1")
    ).json()["estimate"]
    assert estimate["status"] == "abstained"
    assert estimate["reason"] == "rule_does_not_cover_period"


def test_estimate_abstains_when_the_period_splits_two_rules(
    covered: tuple[TestClient, str], migrator_engine: Engine, tmp_path: Path
) -> None:
    client, meter = covered
    _publish(
        migrator_engine,
        tmp_path,
        schedule_dict(effective_end="2026-10-14", resolution_id="SIE-901-2026-TF"),
        schedule_dict(effective_start="2026-10-15", resolution_id="SIE-902-2026-TF"),
    )
    estimate = _get(
        client, meter, _invoice(client, meter, tariff_class="BTS-1")
    ).json()["estimate"]
    assert estimate["reason"] == "period_spans_rules"


def test_a_rule_for_another_distributor_is_not_used(
    covered: tuple[TestClient, str], migrator_engine: Engine, tmp_path: Path
) -> None:
    client, meter = covered
    _publish(migrator_engine, tmp_path, schedule_dict(distributor="EDENORTE"))
    estimate = _get(
        client, meter, _invoice(client, meter, tariff_class="BTS-1")
    ).json()["estimate"]
    assert estimate["reason"] == "no_published_rule"


def test_kwh_between_published_ranges_returns_no_estimate(
    covered: tuple[TestClient, str], migrator_engine: Engine, tmp_path: Path
) -> None:
    client, meter = covered
    _publish(migrator_engine, tmp_path)
    invoice = _invoice(client, meter, tariff_class="BTS-1", billed_kwh="700.5")
    estimate = _get(client, meter, invoice).json()["estimate"]
    assert estimate["reason"] == "kwh_outside_published_bands"


def test_draft_invoice_is_409_and_unknown_is_404(
    covered: tuple[TestClient, str],
) -> None:
    client, meter = covered
    draft = _invoice(client, meter, confirm=False)
    response = _get(client, meter, draft)
    assert response.status_code == 409
    assert response.json()["code"] == "invoice_unconfirmed"
    assert _get(client, meter, str(uuid4())).status_code == 404


def test_owner_isolation_and_wrong_meter_answer_404(app: FastAPI) -> None:
    a, meter_a = _owner(app, "alice")
    b, meter_b = _owner(app, "bruno")
    invoice_a = _invoice(a, meter_a)
    own = _get(a, meter_a, invoice_a)
    assert own.status_code == 200
    # another owner's invoice, on either meter path, and the owner's meter mismatch
    assert _get(b, meter_b, invoice_a).status_code == 404
    assert _get(b, meter_a, invoice_a).status_code == 404
    assert _get(a, meter_b, invoice_a).status_code == 404
    unknown = _get(b, meter_b, str(uuid4()))
    assert unknown.status_code == 404
    assert unknown.json()["code"] == _get(b, meter_b, invoice_a).json()["code"]


def test_route_requires_a_session(app: FastAPI) -> None:
    anonymous = TestClient(app, headers=CSRF)
    response = anonymous.get(
        f"{V1}/meters/{uuid4()}/reconciliation", params={"invoice_id": str(uuid4())}
    )
    assert response.status_code == 401


def test_invoice_id_is_required_and_validated(covered: tuple[TestClient, str]) -> None:
    client, meter = covered
    assert client.get(f"{V1}/meters/{meter}/reconciliation").status_code == 422
    bad = client.get(f"{V1}/meters/{meter}/reconciliation", params={"invoice_id": "x"})
    assert bad.status_code == 422


def test_corrected_confirmed_invoice_uses_the_current_revision(
    covered: tuple[TestClient, str],
) -> None:
    client, meter = covered
    invoice = _invoice(client, meter, billed_kwh="250")
    first = client.get(f"{V1}/invoices/{invoice}").json()["current_revision_id"]
    correction = client.post(
        f"{V1}/invoices/{invoice}/revisions",
        json={
            "base_revision_id": first,
            "expected_current_revision_id": first,
            "billed_kwh": "255",
        },
    )
    assert correction.status_code == 201, correction.text
    # still the confirmed revision until the correction is confirmed
    assert (
        _get(client, meter, invoice).json()["comparison"]["billed_kwh"] == "250.000000"
    )
    draft = correction.json()["revisions"][1]["id"]
    done = client.post(
        f"{V1}/invoices/{invoice}/confirm",
        json={"draft_revision_id": draft, "expected_current_revision_id": first},
    )
    assert done.status_code == 200, done.text
    body = _get(client, meter, invoice).json()
    assert body["revision_id"] == draft
    assert body["comparison"]["difference_kwh"] == "5.000000"
