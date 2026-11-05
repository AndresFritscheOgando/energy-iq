"""Private PDF upload, status, download, retry, and delete (spec 0012/0002).

Synthetic PDFs only. Requests run in the rolled back test transaction, with the
document store pointed at a temporary directory.
"""

import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from dbsupport import CSRF, Clock, Probe, TwoUsers, build_holdings
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pdfsupport import MALFORMED_PDF, NOT_A_PDF, make_pdf, multipart
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from energyiq.documents.reconcile import reconcile
from energyiq.documents.router import get_document_store
from energyiq.documents.storage import LocalDocumentStore
from energyiq.main import create_app
from energyiq.platform.clock import get_now
from energyiq.platform.db import constraint_name, get_db_session
from energyiq.platform.settings import Settings
from energyiq.worker.runner import Worker
from energyiq.worker.sandbox import ChildResult

V1 = "/api/v1"
PDF = make_pdf(1)


@pytest.fixture
def store(tmp_path: Path, db_app: FastAPI) -> LocalDocumentStore:
    documents = LocalDocumentStore(tmp_path / "documents")
    db_app.dependency_overrides[get_document_store] = lambda: documents
    return documents


def _upload(client: TestClient, meter_id: str, data: bytes = PDF, **kwargs: Any) -> Any:
    headers = kwargs.pop("headers", None)
    return client.post(
        f"{V1}/meters/{meter_id}/documents",
        files=multipart(data, **kwargs),
        headers=headers,
    )


def _meter(api: TestClient, owner: dict[str, Any], name: str = "Doc home") -> str:
    return build_holdings(api, owner["id"], name).meter_id


def _files(store: LocalDocumentStore) -> list[Path]:
    root = store.root
    return sorted(path for path in root.rglob("*") if path.is_file())


def _make_worker(
    db_connection: Connection,
    store: LocalDocumentStore,
    clock: Clock,
    parser: Callable[..., ChildResult] | None = None,
    owner: str = "worker-a",
    settings: Settings | None = None,
) -> Worker:
    def factory() -> Session:
        return Session(
            bind=db_connection,
            join_transaction_mode="create_savepoint",
            expire_on_commit=False,
        )

    kwargs: dict[str, Any] = {} if parser is None else {"parser": parser}
    return Worker(
        settings or Settings(env="test"),
        factory,  # pyright: ignore[reportArgumentType]
        store,
        owner=owner,
        now=lambda: clock.now,
        **kwargs,
    )


def _ok(_data: bytes, _limits: object) -> ChildResult:
    return ChildResult(True, None, 1)


def _fail(code: str) -> Callable[[bytes, object], ChildResult]:
    return lambda _data, _limits: ChildResult(False, code)


# AC-1, AC-2: upload, status, download -----------------------------------------


@pytest.mark.db
def test_upload_returns_a_queued_document_with_no_storage_key(
    api: TestClient, owner: dict[str, Any], store: LocalDocumentStore, probe: Probe
) -> None:
    meter = _meter(api, owner)

    response = _upload(api, meter)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["state"] == "uploaded" and body["reason_code"] is None
    assert body["run"]["state"] == "queued" and body["run"]["run_number"] == 1
    assert body["size_bytes"] == len(PDF) and body["meter_id"] == meter
    row = probe.rows("SELECT * FROM source_documents")[0]
    assert body["sha256"] == bytes(row["sha256"]).hex()
    assert str(row["storage_key"]) not in response.text
    assert [path.name for path in _files(store)] == [str(row["storage_key"])]
    assert response.headers["x-request-id"]
    assert [event["action"] for event in probe.audit(body["id"])] == ["document.upload"]
    assert probe.audit(body["id"])[0]["metadata"] == {}


@pytest.mark.db
def test_status_download_and_attachment_headers(
    api: TestClient, owner: dict[str, Any], store: LocalDocumentStore
) -> None:
    document = _upload(api, _meter(api, owner)).json()

    status = api.get(f"{V1}/documents/{document['id']}")
    download = api.get(f"{V1}/documents/{document['id']}/source")

    assert status.status_code == 200 and status.json() == document
    assert download.status_code == 200 and download.content == PDF
    assert download.headers["content-type"] == "application/pdf"
    disposition = download.headers["content-disposition"]
    assert disposition.startswith("attachment;") and ".pdf" in disposition
    assert download.headers["x-content-type-options"] == "nosniff"
    assert download.headers["cache-control"] == "private, no-store"
    assert download.headers["content-security-policy"] == "sandbox"


@pytest.mark.db
def test_a_traversal_file_name_is_ignored(
    api: TestClient, owner: dict[str, Any], store: LocalDocumentStore
) -> None:
    response = _upload(api, _meter(api, owner), filename="../../etc/passwd.pdf")

    assert response.status_code == 201, response.text
    names = [path.name for path in _files(store)]
    assert len(names) == 1 and UUID(names[0])
    assert "passwd" not in response.text


@pytest.mark.db
@pytest.mark.parametrize(
    ("kwargs", "status", "code"),
    [
        ({"filename": "bill.txt"}, 415, "upload_not_pdf"),
        ({"filename": "bill"}, 415, "upload_not_pdf"),
        ({"content_type": "image/png"}, 415, "upload_not_pdf"),
        ({"content_type": "text/plain"}, 415, "upload_not_pdf"),
        ({"field": "attachment"}, 422, "upload_invalid"),
        ({"data": NOT_A_PDF}, 422, "pdf_invalid"),
        ({"data": b"%PDF-1.4 no end marker"}, 422, "pdf_invalid"),
        ({"data": b""}, 422, "upload_invalid"),
    ],
    ids=[
        "wrong extension",
        "no extension",
        "image mime",
        "text mime",
        "wrong field",
        "no signature",
        "no eof marker",
        "empty file",
    ],
)
def test_disguised_and_malformed_uploads_leave_no_file_or_row(
    api: TestClient,
    owner: dict[str, Any],
    store: LocalDocumentStore,
    probe: Probe,
    kwargs: dict[str, Any],
    status: int,
    code: str,
) -> None:
    data = kwargs.pop("data", PDF)

    response = _upload(api, _meter(api, owner), data, **kwargs)

    assert response.status_code == status, response.text
    assert response.json()["code"] == code
    assert _files(store) == []
    assert probe.one("SELECT count(*) FROM source_documents") == 0


@pytest.mark.db
def test_two_file_parts_and_a_non_multipart_body_are_rejected(
    api: TestClient, owner: dict[str, Any], store: LocalDocumentStore
) -> None:
    meter = _meter(api, owner)
    path = f"{V1}/meters/{meter}/documents"

    two = api.post(
        path,
        files=[
            ("file", ("a.pdf", PDF, "application/pdf")),
            ("file", ("b.pdf", PDF, "application/pdf")),
        ],
    )
    as_json = api.post(path, json={"file": "x"})

    assert (two.status_code, two.json()["code"]) == (422, "upload_invalid")
    assert (as_json.status_code, as_json.json()["code"]) == (
        415,
        "unsupported_media_type",
    )
    assert _files(store) == []


# AC-1, AC-5: size caps, declared and streamed ---------------------------------


@pytest.fixture
def small(
    db_session: Session, tmp_path: Path
) -> Iterator[tuple[TestClient, str, LocalDocumentStore]]:
    """An app with a 2000 byte upload cap, a signed in owner, and its meter."""
    settings = Settings(env="test", upload_max_bytes=2000)
    app = create_app(settings)
    documents = LocalDocumentStore(tmp_path / "small")
    clock = Clock()
    app.dependency_overrides[get_db_session] = lambda: db_session
    app.dependency_overrides[get_document_store] = lambda: documents
    app.dependency_overrides[get_now] = lambda: clock.now
    client = TestClient(app, headers=CSRF)
    created = client.post(
        f"{V1}/auth/register",
        json={"email": "small@example.test", "password": "correct horse battery"},
    )
    assert created.status_code == 201, created.text
    meter = build_holdings(client, created.json()["id"], "Small").meter_id
    yield client, meter, documents


def _padded(size: int) -> bytes:
    return b"%PDF-1.4\n" + b"0" * size + b"\n%%EOF\n"


@pytest.mark.db
def test_a_file_over_the_cap_is_rejected_as_it_streams(
    small: tuple[TestClient, str, LocalDocumentStore],
) -> None:
    client, meter, documents = small

    response = _upload(client, meter, _padded(3000))

    assert response.status_code == 413 and response.json()["code"] == "upload_too_large"
    assert _files(documents) == []


@pytest.mark.db
def test_a_declared_length_far_over_the_cap_is_rejected_before_reading(
    small: tuple[TestClient, str, LocalDocumentStore],
) -> None:
    client, meter, documents = small

    response = _upload(client, meter, _padded(200_000))

    assert response.status_code == 413 and response.json()["code"] == "upload_too_large"
    assert _files(documents) == []


@pytest.mark.db
def test_a_chunked_body_without_content_length_is_counted_as_it_streams(
    small: tuple[TestClient, str, LocalDocumentStore],
) -> None:
    client, meter, documents = small
    boundary = "synthetic-boundary"
    head = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=file;"
        ' filename="a.pdf"\r\nContent-Type: application/pdf\r\n\r\n'
    ).encode()
    tail = f"\r\n--{boundary}--\r\n".encode()

    def body() -> Iterator[bytes]:
        yield head
        yield b"%PDF-1.4\n"
        for _ in range(40):  # ~40 KiB: over the file cap, under the framing cap
            yield b"0" * 1000
        yield b"\n%%EOF\n"
        yield tail

    response = client.post(
        f"{V1}/meters/{meter}/documents",
        content=body(),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )

    assert response.status_code == 413 and response.json()["code"] == "upload_too_large"
    assert _files(documents) == []


@pytest.mark.db
def test_a_file_exactly_at_the_cap_is_accepted(
    small: tuple[TestClient, str, LocalDocumentStore],
) -> None:
    client, meter, documents = small
    data = _padded(2000 - len(_padded(0)))
    assert len(data) == 2000

    response = _upload(client, meter, data)

    assert response.status_code == 201, response.text
    assert len(_files(documents)) == 1


# AC-5: ownership, retry keys, limits -----------------------------------------


@pytest.mark.db
def test_foreign_ids_are_404_on_every_document_route(
    two_users: TwoUsers, store: LocalDocumentStore, probe: Probe
) -> None:
    document = _upload(two_users.a.client, two_users.a.meter_id).json()
    before = probe.rows("SELECT * FROM source_documents")
    other = two_users.b.client
    base = f"{V1}/documents/{document['id']}"

    responses = [
        _upload(other, two_users.a.meter_id),
        other.get(base),
        other.get(f"{base}/source"),
        other.post(f"{base}/retry"),
        other.delete(base),
    ]

    for response in responses:
        assert response.status_code == 404, response.text
        assert response.json()["code"] == "not_found"
    assert probe.rows("SELECT * FROM source_documents") == before
    assert len(_files(store)) == 1
    assert two_users.a.client.get(base).json()["state"] == "uploaded"


@pytest.mark.db
def test_upload_replay_returns_the_first_response_and_one_row(
    api: TestClient, owner: dict[str, Any], store: LocalDocumentStore, probe: Probe
) -> None:
    meter = _meter(api, owner)
    headers = {"Idempotency-Key": "upload-one"}

    first = _upload(api, meter, headers=headers)
    second = _upload(api, meter, headers=headers)
    different = _upload(api, meter, make_pdf(2), headers=headers)

    assert first.status_code == 201 and second.status_code == 201
    assert second.json() == first.json()
    assert second.headers["idempotent-replayed"] == "true"
    assert different.status_code == 409
    assert different.json()["code"] == "idempotency_key_reused"
    assert probe.one("SELECT count(*) FROM source_documents") == 1
    assert probe.one("SELECT count(*) FROM extraction_runs") == 1
    assert len(_files(store)) == 1  # replays and conflicts leave no extra file


@pytest.mark.db
def test_an_owner_cannot_hold_more_than_three_active_documents(
    api: TestClient, owner: dict[str, Any], store: LocalDocumentStore
) -> None:
    meter = _meter(api, owner)
    for _ in range(3):
        assert _upload(api, meter).status_code == 201

    over = _upload(api, meter)

    assert over.status_code == 429 and over.json()["code"] == "too_many_active"
    assert len(_files(store)) == 3


@pytest.mark.db
def test_an_inactive_meter_rejects_uploads(
    api: TestClient, owner: dict[str, Any], store: LocalDocumentStore
) -> None:
    meter = _meter(api, owner)
    assert api.post(f"{V1}/meters/{meter}/deactivate").status_code == 200

    response = _upload(api, meter)

    assert response.status_code == 409 and response.json()["code"] == "meter_inactive"
    assert _files(store) == []


@pytest.mark.db
def test_a_second_active_run_for_one_document_is_refused_by_the_database(
    api: TestClient, owner: dict[str, Any], store: LocalDocumentStore, probe: Probe
) -> None:
    document = _upload(api, _meter(api, owner)).json()

    with pytest.raises(IntegrityError) as caught:
        probe.run(
            "INSERT INTO extraction_runs (id, document_id, run_number, state,"
            " attempts, created_at) VALUES (:id, :doc, 2, 'queued', 0, now())",
            {"id": uuid4(), "doc": document["id"]},
        )
    assert constraint_name(caught.value) == "uq_extraction_runs_active_document"


# AC-3: the worker -------------------------------------------------------------


@pytest.mark.db
def test_the_worker_reaches_needs_review_without_creating_an_invoice(
    api: TestClient,
    owner: dict[str, Any],
    store: LocalDocumentStore,
    db_connection: Connection,
    clock: Clock,
    probe: Probe,
) -> None:
    document = _upload(api, _meter(api, owner), make_pdf(2)).json()
    worker = _make_worker(db_connection, store, clock, parser=None)

    assert worker.run_once() is True  # the real isolated child parses the PDF

    status = api.get(f"{V1}/documents/{document['id']}").json()
    assert status["state"] == "needs_review" and status["reason_code"] is None
    assert status["run"]["state"] == "succeeded" and status["run"]["attempts"] == 1
    assert probe.rows("SELECT output FROM extraction_runs")[0]["output"] == {
        "page_count": 2
    }
    assert probe.one("SELECT count(*) FROM invoices") == 0
    assert probe.one("SELECT count(*) FROM invoice_revisions") == 0
    assert worker.run_once() is False


@pytest.mark.db
@pytest.mark.parametrize(
    ("data", "code"),
    [
        (make_pdf(1, password="secret"), "pdf_encrypted"),
        (make_pdf(11), "pdf_too_many_pages"),
        (MALFORMED_PDF, "pdf_malformed"),
    ],
)
def test_a_deterministic_failure_is_final_and_uses_one_attempt(
    api: TestClient,
    owner: dict[str, Any],
    store: LocalDocumentStore,
    db_connection: Connection,
    clock: Clock,
    data: bytes,
    code: str,
) -> None:
    document = _upload(api, _meter(api, owner), data).json()
    worker = _make_worker(db_connection, store, clock, parser=None)

    worker.run_once()

    status = api.get(f"{V1}/documents/{document['id']}").json()
    assert status["state"] == "failed" and status["reason_code"] == code
    assert status["run"]["attempts"] == 1
    assert worker.run_once() is False
    assert store.exists(UUID(_key(db_connection, document["id"])))  # file is kept


def _key(connection: Connection, document_id: str) -> str:
    return str(
        connection.execute(
            text("SELECT storage_key FROM source_documents WHERE id = :id"),
            {"id": document_id},
        ).scalar_one()
    )


@pytest.mark.db
def test_a_lost_lease_cannot_overwrite_the_worker_that_took_over(
    api: TestClient,
    owner: dict[str, Any],
    store: LocalDocumentStore,
    db_connection: Connection,
    clock: Clock,
) -> None:
    document = _upload(api, _meter(api, owner)).json()
    first = _make_worker(db_connection, store, clock, _ok, owner="worker-a")
    second = _make_worker(db_connection, store, clock, _fail("late"), owner="worker-b")
    stale = first.claim()
    assert stale is not None
    assert second.claim() is None  # the lease is still valid

    clock.advance(seconds=91)
    taken = second.claim()
    assert taken is not None and taken.run_id == stale.run_id

    assert first.process(stale) is False  # worker-a finishes late: ignored
    mid = api.get(f"{V1}/documents/{document['id']}").json()
    assert mid["state"] == "processing" and mid["run"]["attempts"] == 2
    assert second.process(taken) is True
    final = api.get(f"{V1}/documents/{document['id']}").json()
    assert final["state"] == "failed" and final["reason_code"] == "late"


@pytest.mark.db
def test_attempts_are_capped_and_expired_leases_recover(
    api: TestClient,
    owner: dict[str, Any],
    store: LocalDocumentStore,
    db_connection: Connection,
    clock: Clock,
) -> None:
    document = _upload(api, _meter(api, owner)).json()
    worker = _make_worker(db_connection, store, clock, _ok)

    assert worker.claim() is not None  # attempt 1, then the process "crashes"
    clock.advance(seconds=91)
    assert worker.claim() is not None  # attempt 2 recovers the expired lease
    clock.advance(seconds=91)
    assert worker.claim() is None  # attempts spent: failed, not claimed

    status = api.get(f"{V1}/documents/{document['id']}").json()
    assert status["state"] == "failed"
    assert status["reason_code"] == "attempts_exhausted"
    assert status["run"]["attempts"] == 2


@pytest.mark.db
def test_a_missing_file_fails_the_run_with_a_stable_code(
    api: TestClient,
    owner: dict[str, Any],
    store: LocalDocumentStore,
    db_connection: Connection,
    clock: Clock,
) -> None:
    document = _upload(api, _meter(api, owner)).json()
    store.delete(UUID(_key(db_connection, document["id"])))

    _make_worker(db_connection, store, clock, _ok).run_once()

    status = api.get(f"{V1}/documents/{document['id']}").json()
    assert status["reason_code"] == "source_missing"


# AC-3, AC-5: retry -----------------------------------------------------------


@pytest.mark.db
def test_retry_creates_a_new_run_until_the_document_limit(
    api: TestClient,
    owner: dict[str, Any],
    store: LocalDocumentStore,
    db_connection: Connection,
    clock: Clock,
    probe: Probe,
) -> None:
    document = _upload(api, _meter(api, owner)).json()
    path = f"{V1}/documents/{document['id']}/retry"
    worker = _make_worker(db_connection, store, clock, _fail("pdf_malformed"))

    active = api.post(path)
    assert active.status_code == 409 and active.json()["code"] == "run_active"
    worker.run_once()
    retry = api.post(path, headers={"Idempotency-Key": "retry-one"})
    replay = api.post(path, headers={"Idempotency-Key": "retry-one"})
    assert retry.status_code == 201 and retry.json()["run"]["run_number"] == 2
    assert retry.json()["state"] == "uploaded"
    assert replay.json() == retry.json()
    assert probe.one("SELECT count(*) FROM extraction_runs") == 2
    worker.run_once()
    third = api.post(path)
    assert third.status_code == 201 and third.json()["run"]["run_number"] == 3
    worker.run_once()

    exhausted = api.post(path)

    assert exhausted.status_code == 409
    assert exhausted.json()["code"] == "retries_exhausted"
    assert probe.one("SELECT count(*) FROM extraction_runs") == 3
    assert [event["action"] for event in probe.audit(document["id"])] == [
        "document.upload",
        "document.retry",
        "document.retry",
    ]


@pytest.mark.db
def test_a_succeeded_run_is_not_retried(
    api: TestClient,
    owner: dict[str, Any],
    store: LocalDocumentStore,
    db_connection: Connection,
    clock: Clock,
) -> None:
    document = _upload(api, _meter(api, owner)).json()
    _make_worker(db_connection, store, clock, _ok).run_once()

    response = api.post(f"{V1}/documents/{document['id']}/retry")

    assert response.status_code == 409 and response.json()["code"] == "run_not_failed"


# AC-4: delete, tombstone, reconcile ------------------------------------------


@pytest.mark.db
def test_delete_removes_the_file_and_derived_data_and_keeps_a_clean_audit(
    api: TestClient,
    owner: dict[str, Any],
    store: LocalDocumentStore,
    db_connection: Connection,
    clock: Clock,
    probe: Probe,
) -> None:
    document = _upload(api, _meter(api, owner)).json()
    _make_worker(db_connection, store, clock, _ok).run_once()
    assert probe.rows("SELECT output FROM extraction_runs")[0]["output"] is not None
    base = f"{V1}/documents/{document['id']}"

    deleted = api.delete(base, headers={"Idempotency-Key": "delete-one"})
    replay = api.delete(base, headers={"Idempotency-Key": "delete-one"})
    again = api.delete(base)

    assert deleted.status_code == 200 and deleted.json()["state"] == "deleted"
    assert replay.json() == deleted.json() and again.json()["state"] == "deleted"
    assert _files(store) == []
    row = probe.rows("SELECT deleted_at, purged_at FROM source_documents")[0]
    assert row["deleted_at"] is not None and row["purged_at"] is not None
    assert probe.rows("SELECT output FROM extraction_runs")[0]["output"] is None
    assert api.get(f"{base}/source").status_code == 404
    assert api.get(base).json()["state"] == "deleted"
    assert api.post(f"{base}/retry").json()["code"] == "document_deleted"
    events = probe.audit(document["id"])
    assert [event["action"] for event in events] == [
        "document.upload",
        "document.delete",
    ]
    assert all(event["metadata"] == {} for event in events)


@pytest.mark.db
def test_delete_fails_a_queued_run_and_waits_for_a_running_one(
    api: TestClient,
    owner: dict[str, Any],
    store: LocalDocumentStore,
    db_connection: Connection,
    clock: Clock,
    probe: Probe,
) -> None:
    meter = _meter(api, owner)
    documents = [_upload(api, meter).json(), _upload(api, meter).json()]
    worker = _make_worker(db_connection, store, clock, _ok)
    claim = worker.claim()  # equal creation times: either run may be first
    assert claim is not None
    claimed_document = probe.one(
        "SELECT document_id FROM extraction_runs WHERE id = :id",
        {"id": claim.run_id},
    )
    running = next(d for d in documents if d["id"] == str(claimed_document))
    queued = next(d for d in documents if d is not running)
    busy = api.delete(f"{V1}/documents/{running['id']}")
    assert busy.status_code == 409 and busy.json()["code"] == "run_active"

    done = api.delete(f"{V1}/documents/{queued['id']}")

    assert done.status_code == 200
    run = probe.rows(
        "SELECT state, error_code FROM extraction_runs WHERE document_id = :id",
        {"id": queued["id"]},
    )[0]
    assert run == {"state": "failed", "error_code": "document_deleted"}
    assert worker.claim() is None  # nothing left to run for a deleted document


@pytest.mark.db
def test_a_document_that_sources_an_invoice_revision_cannot_be_deleted(
    api: TestClient,
    owner: dict[str, Any],
    store: LocalDocumentStore,
    probe: Probe,
) -> None:
    meter = _meter(api, owner)
    document = _upload(api, meter).json()
    invoice = uuid4()
    probe.run(
        "INSERT INTO invoices (id, meter_id, owner_id, created_at)"
        " VALUES (:id, :meter, :owner, now())",
        {"id": invoice, "meter": meter, "owner": owner["id"]},
    )
    probe.run(
        "INSERT INTO invoice_revisions (id, invoice_id, revision_number, status,"
        " actor_id, created_at, source_document_id, field_origins, changed_fields,"
        " old_values) VALUES (:id, :invoice, 1, 'draft', :owner, now(), :doc,"
        " '{}', '[]', '{}')",
        {
            "id": uuid4(),
            "invoice": invoice,
            "owner": owner["id"],
            "doc": document["id"],
        },
    )

    response = api.delete(f"{V1}/documents/{document['id']}")

    assert response.status_code == 409 and response.json()["code"] == "document_in_use"
    assert len(_files(store)) == 1


@pytest.mark.db
def test_reconcile_finds_orphans_and_missing_files_and_repairs_tombstones(
    api: TestClient,
    owner: dict[str, Any],
    store: LocalDocumentStore,
    db_connection: Connection,
    probe: Probe,
    clock: Clock,
) -> None:
    meter = _meter(api, owner)
    live = _upload(api, meter).json()
    gone = _upload(api, meter).json()
    store.delete(UUID(_key(db_connection, gone["id"])))
    orphan = uuid4()
    temp = store.new_temp()
    temp.write_bytes(b"%PDF-")
    store.commit(temp, orphan)
    stale = store.new_temp()
    stale.write_bytes(b"x")
    # A deleted document whose file removal never ran (a crash after the tombstone).
    tombstone = _upload(api, meter).json()
    api.delete(f"{V1}/documents/{tombstone['id']}")
    probe.run(
        "UPDATE source_documents SET purged_at = NULL WHERE id = :id",
        {"id": tombstone["id"]},
    )
    leftover = UUID(_key(db_connection, tombstone["id"]))
    leftover_path = store.open_path(leftover)
    leftover_path.write_bytes(b"%PDF-")

    factory = cast(
        "sessionmaker[Session]",
        lambda: Session(
            bind=db_connection,
            join_transaction_mode="create_savepoint",
            expire_on_commit=False,
        ),
    )
    seconds = time.time() + 3600  # real file times, an hour past the grace period
    young = reconcile(factory, store, clock.now, grace_seconds=300)
    report = reconcile(
        factory, store, clock.now, grace_seconds=300, clock_seconds=seconds
    )

    assert young.orphan_files == [] and young.stale_temp_files == 0
    assert report.orphan_files == [orphan]
    assert report.missing_files == [UUID(gone["id"])]
    assert report.unpurged_tombstones == [UUID(tombstone["id"])]
    assert report.stale_temp_files == 1
    assert store.exists(orphan) and leftover_path.exists()  # report only

    fixed = reconcile(
        factory, store, clock.now, fix=True, grace_seconds=300, clock_seconds=seconds
    )

    assert fixed.fixed and not store.exists(orphan) and not leftover_path.exists()
    assert (
        probe.one(
            "SELECT purged_at IS NOT NULL FROM source_documents WHERE id = :id",
            {"id": tombstone["id"]},
        )
        is True
    )
    assert store.exists(UUID(_key(db_connection, live["id"])))  # the live file stays
    clean = reconcile(
        factory, store, clock.now, grace_seconds=300, clock_seconds=seconds
    )
    assert clean.orphan_files == [] and clean.unpurged_tombstones == []
    assert clean.missing_files == [UUID(gone["id"])]  # not repairable by deleting


# AC-3: two workers racing for one run ----------------------------------------


@pytest.mark.db_commit
def test_two_workers_cannot_claim_one_run(
    committed_db: Engine, db_settings: Settings, tmp_path: Path
) -> None:
    app = create_app(db_settings)
    documents = LocalDocumentStore(tmp_path / "race")
    app.dependency_overrides[get_document_store] = lambda: documents
    client = TestClient(app, headers=CSRF)
    registered = client.post(
        f"{V1}/auth/register",
        json={
            "email": f"claim-{uuid4().hex[:8]}@example.test",
            "password": "correct horse battery",
        },
    )
    assert registered.status_code == 201, registered.text
    meter = build_holdings(client, registered.json()["id"], "Claim").meter_id
    assert _upload(client, meter).status_code == 201
    factory = sessionmaker(bind=committed_db, expire_on_commit=False)
    workers = [
        Worker(db_settings, factory, documents, owner=f"racer-{n}") for n in range(8)
    ]
    barrier = threading.Barrier(len(workers))
    claims: list[object] = []

    def race(worker: Worker) -> None:
        barrier.wait()
        claim = worker.claim()
        if claim is not None:
            claims.append(claim)

    threads = [threading.Thread(target=race, args=(worker,)) for worker in workers]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)

    assert len(claims) == 1
    with committed_db.connect() as connection:
        rows = connection.execute(
            text("SELECT state, attempts, lease_owner FROM extraction_runs")
        ).all()
    assert len(rows) == 1 and rows[0][0] == "running" and rows[0][1] == 1
