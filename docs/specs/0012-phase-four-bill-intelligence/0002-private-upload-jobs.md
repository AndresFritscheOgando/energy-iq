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

**Limits**: Set concrete upload byte, PDF page, text byte, CPU time, memory, attempt, and concurrent run limits before implementation. The current global 1 MiB JSON body cap needs a separately bounded multipart route, not a global increase. Reject encrypted, malformed, or unsupported PDFs with a stable problem code. Do not accept images until their path is designed. Content type and signature checks do not prove safety, so parse in a child process with bounded time and memory and no outbound network access. Verify the available operating system restrictions before claiming filesystem isolation.

**API surface**:

| Path and method | Input | Output | Key errors |
|---|---|---|---|
| `POST /meters/{id}/documents` | PDF multipart, retry key | Document ID, state, run ID | 413 limit, 415 type, 422 PDF |
| `GET /documents/{id}` | Document ID | State and safe reason, run summary | 404 owner |
| `GET /documents/{id}/source` | Document ID | PDF attachment | 404 owner or deleted |
| `POST /documents/{id}/retry` | Retry key | New run ID and state | 409 active or exhausted |
| `DELETE /documents/{id}` | Document ID, retry key | Deleted state | 409 active confirmation review |

**Value sources**: File size and digest come from bytes streamed by the server. Page count comes from the bounded parser. State comes from the run row, never a client value. The response never includes a storage key or raw parser output. Upload replay compares the retry key with a canonical hash of meter ID, SHA-256, and operation, extending the current JSON only idempotency helper for multipart content. The document ID and response are retained for replay.

**Tests**: Use synthetic PDFs and malformed bytes. Cover disguised MIME, traversal name, oversized stream, excessive pages or decompressed text, parser crash, lost lease, double worker claim, upload retry, delete retry, absent file, cross owner reads, and attachment headers.

## Build plan

1. Add document and run migration, isolated directory settings, and storage interface, satisfies **AC-1**, **AC-2**.
2. Add the upload and status routes, then a no model worker that reaches needs review, satisfies **AC-1** to **AC-3**.
3. Add retry, deletion, recovery scan, and abuse tests, satisfies **AC-3** to **AC-5**.

## Consequences

Local storage is simple to run, but file and database changes need a recovery scan. Production hosting must provide durable private storage and backups.

## Rationale

The owner chose retention until deletion. A database backed lease avoids adding a queue to this phase while still making crashes and retries observable.
