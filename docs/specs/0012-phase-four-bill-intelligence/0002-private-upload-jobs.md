# 0002. Private PDF upload and processing runs

## Summary

An owner can upload a PDF for one meter and see its processing state. The original stays private until owner deletion. A failed run can be retried without losing the file or duplicating an invoice.

## Requirements

- **AC-1**: Accept only one bounded PDF per upload after extension, MIME, signature, structure, page count, and size checks. Generate the storage key on the server and keep it outside public paths.
- **AC-2**: Create document metadata and one queued extraction run. Status reads report uploaded, processing, needs review, failed, or deleted and a safe reason code. The owner can download the original as an attachment.
- **AC-3**: A bounded worker claims a run with a database lease. Restart, crash, timeout, and retry cannot create duplicate active work or a confirmed invoice. Attempts are capped and expired leases are recoverable.
- **AC-4**: Owner deletion removes source and derived text/proposals after the metadata tombstone is committed. A reconciliation command finds orphan files and missing files. The remaining audit has no private values.
- **AC-5**: Upload, status, download, retry, and delete reject foreign IDs as 404. CSRF and retry keys protect writes. Tests cover malicious files, resource limits, and concurrent claims.

## Decision

Store bytes in a private local directory with an opaque UUID path and SHA-256 digest. The database owns metadata and run state. A separate local worker process polls and claims rows using PostgreSQL row locks and leases. This fits the one host demo without a broker. Moving to object storage later uses the same document interface.

## Feature design

**Schema**: `SourceDocument` records owner, property, meter, storage key, digest, MIME, size, state, created and deleted UTC times. `ExtractionRun` records document, attempt, state, lease owner and expiry, safe error code, timestamps, model and prompt version, and output. One active run per document is enforced in the database. Use an outbox style recovery scan for a file written but not committed or a committed row whose file is missing.

**Limits**: Each value below is a setting with this default. Settings reject zero, negative, and values above the hard ceiling, so a typo cannot disable a cap. A bill from a utility is normally a few hundred KiB and one to four pages, so the defaults leave room without inviting abuse.

| Limit | Setting | Default | Hard ceiling | Failure code |
|---|---|---|---|---|
| Upload file bytes | `ENERGYIQ_UPLOAD_MAX_BYTES` | 5 MiB (5242880) | 20 MiB | `upload_too_large` (413) |
| PDF pages | `ENERGYIQ_PDF_MAX_PAGES` | 10 | 50 | `pdf_too_many_pages` |
| Extracted text bytes, all pages, UTF-8 after normalization | `ENERGYIQ_PDF_MAX_TEXT_BYTES` | 256 KiB (262144) | 1 MiB | `pdf_text_too_large` |
| Child CPU seconds | `ENERGYIQ_PDF_CPU_SECONDS` | 20 | 60 | `pdf_parse_timeout` |
| Child wall clock seconds | `ENERGYIQ_PDF_WALL_SECONDS` | 30 | 120 | `pdf_parse_timeout` |
| Child memory (address space) | `ENERGYIQ_PDF_MEMORY_BYTES` | 768 MiB | 2 GiB | `pdf_parse_resource` |
| Attempts per run (first try plus crash or lease recovery) | `ENERGYIQ_RUN_MAX_ATTEMPTS` | 2 | 5 | run `failed`, `attempts_exhausted` |
| Runs per document (first run plus owner retries) | `ENERGYIQ_DOC_MAX_RUNS` | 3 | 10 | 409 `retries_exhausted` |
| Concurrent runs, whole worker | `ENERGYIQ_WORKER_CONCURRENCY` | 1 | 4 | queued runs wait |
| Active documents per owner (uploaded or processing) | `ENERGYIQ_OWNER_MAX_ACTIVE_DOCS` | 3 | 10 | 429 `too_many_active` |
| Run lease seconds | `ENERGYIQ_RUN_LEASE_SECONDS` | 90 | 600 | lease expires, run recoverable |

Rules for these values:

- The lease must be longer than the wall clock limit plus parent overhead. Settings validation rejects a lease at or below the wall clock limit plus 30 seconds.
- A text limit breach fails the run with `pdf_text_too_large`. The parser never truncates silently, because a cut bill could hide the total.
- Deterministic outcomes (encrypted, malformed, too many pages, text too large, timeout, resource) are final for that run and do not consume a second attempt. Only a worker crash or an expired lease does. An owner retry starts a new run, up to the runs per document limit.
- The current global 1 MiB JSON body cap stays. The upload route gets its own cap of the file limit plus 64 KiB for multipart framing. It rejects an oversized `Content-Length` before reading, and it also counts streamed bytes, because the header can be absent or wrong. The file is written to a temporary name in the document root and renamed only after the checks pass. A rejected stream leaves no file.
- Reject encrypted (even with an empty password), malformed, and non PDF files with a stable problem code. Do not accept images until their path is designed.

**Parse isolation**: Content type and signature checks do not prove safety, and `pypdf` has had denial of service fixes (an infinite loop and decompression limits), so parsing never runs in the API process or the worker process itself.

- The worker parent reads the stored file and starts one child per run with `python -I -m` on a small parser module. The parent sends the PDF bytes on stdin and reads one JSON result from stdout, capped at 1 MiB. The child gets no file path, no database, and an empty environment with no secrets. Standard error is discarded and never logged.
- On Linux, the child sets limits before it opens the PDF: `RLIMIT_CPU`, `RLIMIT_AS` from the memory setting, `RLIMIT_FSIZE` of zero so it cannot write files, `RLIMIT_NOFILE` of 16, and `RLIMIT_CORE` of zero. The parent also enforces the wall clock limit, kills the whole process group on expiry, and records the failure code. A killed child never leaves a partial result, because the parent only accepts a complete valid JSON document.
- The supported secure mode is a Linux container for the worker. It runs as a non root user, with a read only root filesystem, a small tmpfs for temporary files, all capabilities dropped, `no-new-privileges`, a container memory limit of 1 GiB, and a process count limit. Only the worker mounts the document root.
- The child runs under the same uid as the worker parent, so the parent calls `prctl(PR_SET_DUMPABLE, 0)` at start in container mode on Linux (development mode skips it). That makes `/proc/<ppid>/environ` and ptrace closed to the child, which protects the database URL and password. Residual risk: the child shares the container filesystem view, so a compromised parser could read any owner's PDF under the read only document root. Mitigations are the empty environment, no network route, and no write access. Per run file isolation is not built.
- Outbound network access is closed at the container network. The worker joins an internal Docker network that holds only PostgreSQL, so it has no route to the internet. The child has no database password and no environment, so it has nothing to use even though it shares that network. Child level network namespaces need extra privileges and are not used. Spec 0004 reaches Ollama only from the worker parent, never from the parse child, and must add a separate network entry for it without opening the internet.
- A Windows or other direct run is a development mode only. It still uses the child process, the wall clock timeout, and the output cap, but has no memory, network, or filesystem isolation. `ENERGYIQ_WORKER_ISOLATION` is `container` or `none`. `none` is accepted only when `ENERGYIQ_ENV` names a development or test environment. In any other environment the worker refuses to start.
- Claims about isolation stay `not run` until a container test shows these results: an outbound connection from the child fails, a synthetic memory bomb and an infinite loop PDF are killed within the limits, and the child cannot write a file.

**API surface**:

| Path and method | Input | Output | Key errors |
|---|---|---|---|
| `POST /meters/{id}/documents` | PDF multipart, retry key | Document ID, state, run ID | 413 limit, 415 type, 422 PDF |
| `GET /documents/{id}` | Document ID | State and safe reason, run summary | 404 owner |
| `GET /documents/{id}/source` | Document ID | PDF attachment | 404 owner or deleted |
| `POST /documents/{id}/retry` | Retry key | New run ID and state | 409 active or exhausted |
| `DELETE /documents/{id}` | Document ID, retry key | Deleted state | 409 active confirmation review |

**Value sources**: File size and digest come from bytes streamed by the server. Page count comes from the bounded parser. State comes from the run row, never a client value. The response never includes a storage key or raw parser output. Upload replay compares the retry key with a canonical hash of meter ID, SHA-256, and operation, extending the current JSON only idempotency helper for multipart content. The document ID and response are retained for replay.

**Tests**: Use synthetic PDFs and malformed bytes. Cover disguised MIME, traversal name, oversized stream with and without a correct `Content-Length`, excessive pages or decompressed text, parser crash, CPU loop, memory bomb, child output over the cap, lost lease, double worker claim, attempts exhausted, runs per document exhausted, owner active document limit, upload retry, delete retry, absent file, cross owner reads, and attachment headers. Container only tests for network, memory, and write denial are marked so they skip with a visible reason outside Linux.

## Build plan

1. Add document and run migration, isolated directory settings, and storage interface, satisfies **AC-1**, **AC-2**.
2. Add the upload and status routes, then a no model worker that reaches needs review, satisfies **AC-1** to **AC-3**.
3. Add retry, deletion, recovery scan, and abuse tests, satisfies **AC-3** to **AC-5**.

## Consequences

Local storage is simple to run, but file and database changes need a recovery scan. Production hosting must provide durable private storage and backups. The worker needs a Compose service and an internal network, which adds a little setup. Developers on Windows get a weaker mode that cannot process real uploads in production.

## Rationale

The owner chose retention until deletion. A database backed lease avoids adding a queue to this phase while still making crashes and retries observable.
