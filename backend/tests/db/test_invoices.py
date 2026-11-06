"""Manual invoice journey with synthetic values only (spec 0012/0001)."""

from collections.abc import Callable
from typing import Any

import pytest
from dbsupport import Probe, TwoUsers, build_holdings
from fastapi.testclient import TestClient


def _draft(start: str = "2026-10-01", end: str = "2026-10-31") -> dict[str, str]:
    return {
        "distributor": "EDESUR",
        "period_start": start,
        "period_end": end,
        "billed_kwh": "123.456789",
        "total_dop": "999.01",
    }


@pytest.mark.db
def test_draft_confirm_correct_history_and_replay(
    api: TestClient, owner: dict[str, Any]
) -> None:
    meter = build_holdings(api, owner["id"], "Invoice home").meter_id
    path = f"/api/v1/meters/{meter}/invoices"
    draft = api.post(path, json=_draft(), headers={"Idempotency-Key": "invoice-one"})
    assert draft.status_code == 201, draft.text
    assert draft.json()["revisions"][0]["field_origins"]["total_dop"] == "manual"
    replay = api.post(path, json=_draft(), headers={"Idempotency-Key": "invoice-one"})
    assert replay.status_code == 201 and replay.headers["Idempotent-Replayed"] == "true"
    assert replay.json() == draft.json()
    invoice = draft.json()
    invoice_id = invoice["id"]
    first_id = invoice["revisions"][0]["id"]
    confirmed = api.post(
        f"/api/v1/invoices/{invoice_id}/confirm",
        json={"draft_revision_id": first_id, "expected_current_revision_id": None},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["current_revision_id"] == first_id
    correction = api.post(
        f"/api/v1/invoices/{invoice_id}/revisions",
        json={
            "base_revision_id": first_id,
            "expected_current_revision_id": first_id,
            "total_dop": "1001.02",
        },
    )
    assert correction.status_code == 201, correction.text
    revised = correction.json()["revisions"][1]
    assert revised["old_values"] == {"total_dop": "999.01"}
    assert revised["changed_fields"] == ["total_dop"]
    assert revised["field_origins"]["total_dop"] == "manual"
    final = api.post(
        f"/api/v1/invoices/{invoice_id}/confirm",
        json={
            "draft_revision_id": revised["id"],
            "expected_current_revision_id": first_id,
        },
    )
    assert final.status_code == 200, final.text
    assert final.json()["current_revision_id"] == revised["id"]
    assert final.json()["revisions"][0]["total_dop"] == "999.01"
    assert final.json()["revisions"][1]["total_dop"] == "1001.02"


@pytest.mark.db
def test_overlap_and_owner_isolation(
    two_users: TwoUsers,
    new_client: Callable[[], TestClient],
    register: Callable[..., dict[str, Any]],
) -> None:
    a, b = new_client(), new_client()
    register(a, "invoice-a@example.test")
    register(b, "invoice-b@example.test")
    meter_a = build_holdings(a, two_users.a.user_id, "Invoice A").meter_id
    meter_b = build_holdings(b, two_users.b.user_id, "Invoice B").meter_id
    path_a = f"/api/v1/meters/{meter_a}/invoices"
    first = a.post(path_a, json=_draft()).json()
    assert b.get(path_a).status_code == 404
    assert b.get(f"/api/v1/invoices/{first['id']}").status_code == 404
    assert (
        b.post(
            f"/api/v1/invoices/{first['id']}/confirm",
            json={
                "draft_revision_id": first["revisions"][0]["id"],
                "expected_current_revision_id": None,
            },
        ).status_code
        == 404
    )
    assert (
        a.post(
            f"/api/v1/invoices/{first['id']}/confirm",
            json={
                "draft_revision_id": first["revisions"][0]["id"],
                "expected_current_revision_id": None,
            },
        ).status_code
        == 200
    )
    second = a.post(path_a, json=_draft("2026-10-31", "2026-11-01")).json()
    overlap = a.post(
        f"/api/v1/invoices/{second['id']}/confirm",
        json={
            "draft_revision_id": second["revisions"][0]["id"],
            "expected_current_revision_id": None,
        },
    )
    assert (
        overlap.status_code == 409
        and overlap.json()["code"] == "invoice_period_overlap"
    )
    assert (
        b.post(f"/api/v1/meters/{meter_b}/invoices", json=_draft()).status_code == 201
    )


@pytest.mark.db
def test_partial_draft_and_invalid_values(
    api: TestClient, owner: dict[str, Any]
) -> None:
    meter = build_holdings(api, owner["id"], "Validation home").meter_id
    path = f"/api/v1/meters/{meter}/invoices"
    partial = api.post(path, json={"total_dop": "0.01"})
    assert partial.status_code == 201, partial.text
    invoice = partial.json()
    incomplete = api.post(
        f"/api/v1/invoices/{invoice['id']}/confirm",
        json={
            "draft_revision_id": invoice["revisions"][0]["id"],
            "expected_current_revision_id": None,
        },
    )
    assert incomplete.status_code == 422
    assert incomplete.json()["code"] == "invoice_incomplete"
    for bad in (
        {"total_dop": "1.001"},
        {"billed_kwh": "1.1234567"},
        {"period_start": "2026-11-02", "period_end": "2026-11-01"},
        {"total_dop": -1},
    ):
        assert api.post(path, json=bad).status_code == 422


def _revise(
    api: TestClient, invoice: dict[str, Any], expected: str | None, **fields: str
) -> Any:
    return api.post(
        f"/api/v1/invoices/{invoice['id']}/revisions",
        json={
            "base_revision_id": invoice["revisions"][-1]["id"],
            "expected_current_revision_id": expected,
            **fields,
        },
    )


@pytest.mark.db
def test_partial_draft_completes_over_revisions_then_confirms(
    api: TestClient, owner: dict[str, Any]
) -> None:
    meter = build_holdings(api, owner["id"], "Stepwise home").meter_id
    path = f"/api/v1/meters/{meter}/invoices"
    invoice = api.post(path, json={"total_dop": "10.50"}).json()
    steps = (
        {"distributor": "EDESUR", "period_start": "2026-10-01"},
        {"period_end": "2026-10-31", "billed_kwh": "100"},
    )
    for number, step in enumerate(steps, start=2):
        response = _revise(api, invoice, None, **step)
        assert response.status_code == 201, response.text
        invoice = response.json()
        latest = invoice["revisions"][-1]
        assert latest["revision_number"] == number
        assert latest["changed_fields"] == sorted(step)
        assert latest["previous_revision_id"] == invoice["revisions"][-2]["id"]
        assert latest["total_dop"] == "10.50"
        assert latest["field_origins"]["total_dop"] == "manual"
    assert invoice["current_revision_id"] is None
    assert len(invoice["revisions"]) == 3
    confirmed = api.post(
        f"/api/v1/invoices/{invoice['id']}/confirm",
        json={
            "draft_revision_id": invoice["revisions"][-1]["id"],
            "expected_current_revision_id": None,
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    body = confirmed.json()
    assert body["current_revision_id"] == invoice["revisions"][-1]["id"]
    assert [r["status"] for r in body["revisions"]] == ["draft", "draft", "confirmed"]
    old = api.post(
        f"/api/v1/invoices/{invoice['id']}/confirm",
        json={
            "draft_revision_id": invoice["revisions"][0]["id"],
            "expected_current_revision_id": None,
        },
    )
    assert old.status_code == 409


@pytest.mark.db
def test_stale_base_revision_is_rejected(
    api: TestClient, owner: dict[str, Any]
) -> None:
    meter = build_holdings(api, owner["id"], "Stale home").meter_id
    invoice = api.post(f"/api/v1/meters/{meter}/invoices", json=_draft()).json()
    first = invoice["revisions"][0]["id"]
    assert _revise(api, invoice, None, total_dop="20.00").status_code == 201
    stale = api.post(
        f"/api/v1/invoices/{invoice['id']}/revisions",
        json={
            "base_revision_id": first,
            "expected_current_revision_id": None,
            "total_dop": "30.00",
        },
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "stale_invoice_revision"
    wrong_pointer = _revise(api, invoice, first, total_dop="30.00")
    assert wrong_pointer.status_code == 409
    after = api.get(f"/api/v1/invoices/{invoice['id']}").json()
    assert len(after["revisions"]) == 2
    missing = api.post(
        f"/api/v1/invoices/{invoice['id']}/revisions",
        json={"expected_current_revision_id": None, "total_dop": "1.00"},
    )
    assert missing.status_code == 422


@pytest.mark.db
def test_edit_while_correction_draft_is_open(
    api: TestClient, owner: dict[str, Any]
) -> None:
    meter = build_holdings(api, owner["id"], "Open correction").meter_id
    invoice = api.post(f"/api/v1/meters/{meter}/invoices", json=_draft()).json()
    first = invoice["revisions"][0]["id"]
    invoice = api.post(
        f"/api/v1/invoices/{invoice['id']}/confirm",
        json={"draft_revision_id": first, "expected_current_revision_id": None},
    ).json()
    invoice = _revise(api, invoice, first, total_dop="50.00").json()
    again = _revise(api, invoice, first, billed_kwh="7")
    assert again.status_code == 201, again.text
    latest = again.json()["revisions"][-1]
    assert latest["total_dop"] == "50.00" and latest["billed_kwh"] == "7.000000"
    assert latest["old_values"] == {"billed_kwh": "123.456789"}
    final = api.post(
        f"/api/v1/invoices/{invoice['id']}/confirm",
        json={
            "draft_revision_id": latest["id"],
            "expected_current_revision_id": first,
        },
    )
    assert final.status_code == 200, final.text
    assert final.json()["current_revision_id"] == latest["id"]
    bad = _revise(api, final.json(), latest["id"], period_start="2026-12-01")
    assert bad.status_code == 422


@pytest.mark.db
def test_audit_records_field_names_never_values(
    api: TestClient, owner: dict[str, Any], probe: Probe
) -> None:
    meter = build_holdings(api, owner["id"], "Audit home").meter_id
    invoice = api.post(f"/api/v1/meters/{meter}/invoices", json=_draft()).json()
    revised = _revise(api, invoice, None, total_dop="777.77").json()
    latest = revised["revisions"][-1]["id"]
    confirmed = api.post(
        f"/api/v1/invoices/{invoice['id']}/confirm",
        json={"draft_revision_id": latest, "expected_current_revision_id": None},
    )
    assert confirmed.status_code == 200, confirmed.text
    events = probe.audit(invoice["id"])
    by_action = {event["action"]: event["metadata"] for event in events}
    assert set(by_action) == {"invoice.create", "invoice.correct", "invoice.confirm"}
    assert by_action["invoice.correct"] == {"fields": ["total_dop"]}
    assert by_action["invoice.confirm"]["revision_id"] == latest
    assert "999.01" not in str(events) and "777.77" not in str(events)


@pytest.mark.db
def test_correction_that_changes_nothing_is_rejected(
    api: TestClient, owner: dict[str, Any]
) -> None:
    meter = build_holdings(api, owner["id"], "No change home").meter_id
    invoice = api.post(f"/api/v1/meters/{meter}/invoices", json=_draft()).json()
    same = _revise(api, invoice, None, billed_kwh="123.456789", total_dop="999.01")
    assert same.status_code == 422
    assert same.json()["code"] == "empty_correction"
    padded = _revise(api, invoice, None, billed_kwh="123.4567890")
    assert padded.status_code == 422
    mixed = _revise(api, invoice, None, billed_kwh="123.456789", total_dop="5.00")
    assert mixed.status_code == 201, mixed.text
    latest = mixed.json()["revisions"][-1]
    assert latest["changed_fields"] == ["total_dop"]
    assert latest["old_values"] == {"total_dop": "999.01"}
    assert len(mixed.json()["revisions"]) == 2


@pytest.mark.db
def test_list_returns_each_invoice_with_its_own_history(
    api: TestClient, owner: dict[str, Any]
) -> None:
    meter = build_holdings(api, owner["id"], "List home").meter_id
    path = f"/api/v1/meters/{meter}/invoices"
    first = api.post(path, json=_draft("2026-01-01", "2026-01-31")).json()
    second = api.post(path, json=_draft("2026-02-01", "2026-02-28")).json()
    assert _revise(api, second, None, total_dop="1.00").status_code == 201
    listed = {item["id"]: item for item in api.get(path).json()["items"]}
    assert len(listed[first["id"]]["revisions"]) == 1
    assert [r["revision_number"] for r in listed[second["id"]]["revisions"]] == [1, 2]
