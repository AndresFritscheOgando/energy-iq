# Verify: Phase 4 bill intelligence · spec 0012 · updated 2026-11-05
_Steps derived from spec 0012 child 0002 (private upload and processing runs). `/check verify` runs these; `/test` locks the durable ones. Children 0001, 0003 to 0006 add their own sections._

## Child 0002 · Private PDF upload and processing runs

### API / manual (needs the dev database, `uvicorn`, and `PYTHONPATH=backend/src` for the worker)
- [ ] Register, create a property and meter, then `POST /api/v1/meters/{id}/documents` with a one page synthetic PDF → 201, `state: uploaded`, `run.state: queued`, no `storage_key` anywhere in the body, `sha256` equals the file's SHA-256 → AC-1, AC-2
- [ ] Look in `ENERGYIQ_DOCUMENT_ROOT` → one file named by a UUID under `objects/`, nothing in `tmp/`, and the root is outside `frontend/` and any served path → AC-1
- [ ] Upload with file name `../../x.pdf` → stored under a UUID name; the response and the directory show no trace of the client name → AC-1
- [x] Upload `bill.txt`, a `.pdf` named part typed `image/png`, a text file named `.pdf`, a PDF without `%%EOF`, an empty file, two file parts, a part named `attachment`, and a JSON body → 415, 415, 422 `pdf_invalid`, 422 `pdf_invalid`, 422 `upload_invalid`, 422 `upload_invalid`, 422 `upload_invalid`, 415; no file left in `objects/` or `tmp/` → AC-1, AC-5 (ran live 2026-11-05: 415, 415, 422, 422, 422, 422 for the attachment field, 415 for the JSON body; also two file parts 422; no tmp files left)
- [x] Set `ENERGYIQ_UPLOAD_MAX_BYTES=2000`; upload 3000 bytes (counted while streaming), 200 KB (declared length), and a chunked body with no `Content-Length` → three 413 `upload_too_large`, no file left; a file of exactly 2000 bytes → 201 → AC-1, AC-5 (ran live: 3000 streamed, 200 KB, and a chunked body with no length all 413 `upload_too_large`; a valid file of exactly 2000 bytes 201, though it later failed `pdf_malformed` because my hand padding shifted PDF offsets)
- [x] Set `ENERGYIQ_UPLOAD_MAX_BYTES=0`, `-1`, and `20971521` → the app refuses to start naming `upload_max_bytes`; repeat for each setting in the limits table at its ceiling plus one → AC-1 (ran: 0, -1, 20971521 refused naming `upload_max_bytes`; every other limit refused at its ceiling plus one)
- [x] Set `ENERGYIQ_RUN_LEASE_SECONDS=60` with the default 30 second wall clock → startup fails naming the lease rule; 61 starts → AC-3 (ran: 60 refused with `lease_too_short`, 61 starts)
- [ ] `GET /documents/{id}` → state and run summary; `GET /documents/{id}/source` → bytes equal the upload, `Content-Disposition: attachment`, `application/pdf`, `X-Content-Type-Options: nosniff`, `Content-Security-Policy: sandbox`, `Cache-Control: private, no-store` → AC-2
- [ ] Sign in as a second owner and call the upload (on the first owner's meter), status, source, retry, and delete routes with the first owner's IDs → every one 404 `not_found` with the same body as a random ID; nothing changed in the database or the directory → AC-5
- [x] Send each write without the `X-EnergyIQ-CSRF` header, and with a foreign `Origin` → 403 `csrf_rejected` → AC-5 (ran: no header 403, foreign Origin 403 `csrf_rejected`)
- [x] Repeat one upload with the same `Idempotency-Key` → same response with `Idempotent-Replayed: true`, one document row, one run row, one file; reuse the key with a different file → 409 `idempotency_key_reused`, no extra file → AC-5 (ran live 2026-11-05: replay 201 twice, `Idempotent-Replayed: true`, same ID; other file 409 `idempotency_key_reused`)
- [x] Upload three PDFs without running the worker, then a fourth → 429 `too_many_active`; the fourth leaves no file → AC-5 (ran live 2026-11-05: fourth upload 429 `too_many_active`)
- [ ] Deactivate the meter, then upload → 409 `meter_inactive`, no file → AC-1

### Worker (run `PYTHONPATH=backend/src uv run python -m energyiq.worker`)
- [ ] With the worker running, a one page PDF goes `uploaded` → `processing` → `needs_review` within a few seconds; `extraction_runs.output` is `{"page_count": 1}`; the `invoices` and `invoice_revisions` tables stay empty → AC-3
- [ ] Upload a password protected PDF (user password set, and one with an empty password), an 11 page PDF, and a broken PDF → `failed` with `pdf_encrypted`, `pdf_encrypted`, `pdf_too_many_pages`, `pdf_malformed`; each run shows `attempts: 1`; the original is still downloadable → AC-1, AC-3
- [ ] Kill the worker process while a run is `running` (pause the child with a breakpoint or a long running synthetic file), wait past `ENERGYIQ_RUN_LEASE_SECONDS`, restart → the run is claimed again with `attempts: 2` and finishes; kill it twice more → `failed` with `attempts_exhausted`, never a third attempt → AC-3
- [x] Start two worker processes against one queued run → exactly one claims it (`lease_owner` names one process; `attempts` is 1) → AC-3 (ran live with three queued runs and two local workers: three runs, each `attempts: 1`, no failures, none run twice)
- [ ] Delete the stored file by hand and run the worker → run fails with `source_missing` → AC-3, AC-4
- [x] `ENERGYIQ_ENV=prod ENERGYIQ_WORKER_ISOLATION=none` with valid prod settings → the worker exits 2 and says dev or test only; `ENERGYIQ_WORKER_ISOLATION=container` starts → AC-3 (ran: exit 2 with the dev or test message; the container value was proven by the running compose worker)

### Retry and delete
- [ ] `POST /documents/{id}/retry` while a run is queued or running → 409 `run_active`; after a failure → 201 with `run_number: 2`; replay with the same key → same response, one new run; after the third run fails → 409 `retries_exhausted` and no fourth run row; after a success → 409 `run_not_failed` → AC-3, AC-5
- [x] `DELETE /documents/{id}` after a success → 200 `state: deleted`; file gone from `objects/`; `purged_at` set; `extraction_runs.output` is NULL; `GET .../source` → 404; `GET /documents/{id}` still shows `deleted`; a second delete (with and without a key) → 200 → AC-4 (ran live: 200 deleted, output cleared, file gone, source 404, second delete 200 with and without a key)
- [ ] `audit_events` for the document hold only `document.upload` and `document.delete` with empty metadata, and no file name, hash, or text → AC-4
- [ ] Delete while a run is `running` → 409 `run_active`; delete while `queued` → 200 and the run is `failed` with `document_deleted`, and the worker never claims it → AC-3, AC-4
- [ ] Insert an `invoice_revisions` row whose `source_document_id` is the document, then delete → 409 `document_in_use`, file kept → AC-4
- [ ] Simulate a crash after the tombstone: set `purged_at` to NULL on a deleted document and put the file back; run `PYTHONPATH=backend/src uv run python -m energyiq.documents.reconcile` → lists it under `unpurged_tombstones`, changes nothing; with `--fix` the file is removed and `purged_at` is set → AC-4
- [x] Copy a stray file named by a UUID into `objects/`, set its modified time past five minutes ago, run reconcile → `orphan_files: 1`; a stray file younger than five minutes is not listed; `--fix` removes the old one → AC-4 (ran live: the 10 minute old file listed as `orphan_files: 1`, the new one not, `--fix` removed only the old one)
- [ ] Remove a live document's file and run reconcile → `missing_files` lists the document ID and exit code is 1, even with `--fix` → AC-4

### Isolation (Linux container; run with the `worker` image)
- [x] `docker build -f infra/worker.Dockerfile -t energyiq-worker:test .` then run the parse child inside it with `--network <internal network> --read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges:true --memory 1g --pids-limit 64 --user 10001:10001` → an outbound connection to a public address fails, an address space bomb is killed, an infinite loop is killed at the wall clock limit, a child file write is refused, the root filesystem is read only, a real one page PDF still parses → AC-3 (isolation claim) (ran in the running compose container 2026-11-05: outbound connect fails, root filesystem read only, no capabilities, uid 10001, infinite loop `pdf_parse_timeout`, memory and write mimics fail; the real parse path worked. The memory bomb and write checks use the unit test mimic, not a hostile PDF.)
- [x] `docker compose -f infra/compose.yaml --profile worker up -d worker` against the Compose database, then upload through the API and watch the run reach `needs review` from inside the container → AC-3 (not yet run) (ran live 2026-11-05: nine uploads reached `needs_review` or `failed` inside the rebuilt container)

## Commands
- [ ] `ENERGYIQ_REQUIRE_DB=1 uv run pytest` → all pass, only the two Linux only child tests skipped with a reason on Windows → AC-1 to AC-5
- [ ] `uv run pytest backend/tests/db/test_documents.py backend/tests/test_document_worker_units.py -q` → 68 passed, 2 skipped → AC-1 to AC-5
- [ ] `uv run alembic upgrade head`, `uv run alembic downgrade 0004`, `uv run alembic upgrade head`, `uv run alembic check` → clean, "No new upgrade operations detected" → AC-2
- [ ] `uv run ruff check backend`, `uv run ruff format --check backend`, `uv run pyright` → no findings, 0 errors → all

## Acceptance-criteria coverage
- AC-1 (bounded PDF, server key, private path) … steps for upload, name, rejects, caps, settings, store location
- AC-2 (metadata, one queued run, status, attachment download) … upload, status, download steps
- AC-3 (lease claim, restart, crash, attempts, no duplicate work, no invoice) … worker steps, lease setting, double worker, retry
- AC-4 (delete after tombstone, reconcile, clean audit) … delete, audit, reconcile steps
- AC-5 (foreign IDs 404, CSRF and retry keys, malicious files, limits, concurrent claims) … ownership, CSRF, replay, limits, double worker steps

## Child 0003 · PDF native text (P4-03, steps 1 and 2)

### Worker (live, 2026-11-05, rebuilt worker container against the dev database)
- [x] Upload a 2 page text PDF, a scan, a text then scan PDF, a rotated PDF, and a PDF with hidden text → all `needs_review`; `extraction_runs.output` holds `pages` with `has_text` or `empty`, `normalization: n1`, and `native_text` true except for the scan → AC-1, AC-2
- [x] The hidden instruction string is stored as ordinary page text and no field, action, or invoice appears (`invoices` count for these meters is 0) → AC-1, AC-2
- [x] Upload an encrypted PDF, an 11 page PDF, a malformed PDF, and a PDF with about 300 KB of text → `failed` with `pdf_encrypted`, `pdf_too_many_pages`, `pdf_malformed`, `pdf_text_too_large`; no pages stored; each original still downloads byte for byte → AC-2
- [x] `GET /documents/{id}` returns no page text, `normalized_text`, or storage key; delete clears `output`, removes the file, and source returns 404 → AC-1
- [x] A second owner gets 404 on get, source, delete, retry, and upload to the first owner's meter; a write without the CSRF header gets 403 → AC-2

### Commands
- [x] `uv run python backend/evals/native_text.py` → 12 cases, 42 of 47 strings, 0 of 6 blank pages with text, 1 hidden string extracted; report in `docs/evals/native-text-baseline.md` → AC-3
- [x] `ENERGYIQ_REQUIRE_DB=1 uv run pytest` → 1112 passed, 2 skipped; Ruff and Pyright clean → AC-1 to AC-3
- [ ] OCR or vision candidate measured on the same corpus → AC-4 (not run; no fallback enabled)

_Still not run live (covered only by the automated suite): crash and lease recovery with `attempts_exhausted`, delete while running, `document_in_use`, `meter_inactive`, identical 404 bodies for foreign and random IDs, source download headers, the audit event contents, reconcile `unpurged_tombstones` and `missing_files` simulations, and a hostile PDF for memory and file write limits. Reconcile also reports 11 missing files from an earlier session account (`v1-cb4fb6`), none from this run._
