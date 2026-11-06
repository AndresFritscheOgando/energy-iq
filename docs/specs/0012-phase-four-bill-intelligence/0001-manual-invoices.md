# 0001. Manual invoices and source history

## Summary

You can save an invoice draft for one meter and confirm it after review. Later corrections create a new revision. The original values and their source stay visible.

## Requirements

- **AC-1**: The owner creates and lists drafts for one active owned meter. Distributor, inclusive local period dates, billed kWh, DOP total, optional energy charge, issue date, and due date are stored separately. Drafts may be incomplete. The owner can keep revising a draft until it is complete enough to confirm.
- **AC-2**: Confirmation validates distributor, period order, billed kWh, DOP total, and field origins. It locks the meter and invoice, rejects a stale revision or overlap with another current confirmed period, and writes the audit and current pointer in one transaction.
- **AC-3**: Every change after the first save creates a new draft revision that copies the latest revision, whether that one is a draft or confirmed, and applies only the submitted fields. An invoice that was never confirmed can therefore be completed in steps. Only the latest revision can be confirmed. Confirmation makes it current and retains every former revision. A write based on anything but the latest revision is rejected as stale. Reads show revision number, author, UTC times, changed field names, and old values.
- **AC-4**: Foreign meter and invoice IDs return 404. Lists paginate. POST retry keys replay one result. All writes require CSRF and audit, with no private values in audit metadata.

## Decision

Use `Invoice` as the stable identity and immutable `InvoiceRevision` rows for all content. A current revision pointer selects the public view. A confirmed revision is never updated. A corrected draft can overlap its own current revision but cannot become current if another invoice overlaps. Editing a draft never updates a row. It appends a revision whose `previous_revision_id` is the latest revision, so a superseded draft stays as history and is never confirmable. This replaces the earlier rule that refused a new revision while a draft was open (`draft_already_exists`).

## Feature design

**Schema and invariants**: `Invoice(id, meter_id, owner_id, current_revision_id, created_at)` has many `InvoiceRevision(id, invoice_id, revision_number, status, actor_id, created_at, confirmed_at, distributor, period_start, period_end, billed_kwh, total_dop, energy_charge_dop, issue_date, due_date, source_document_id, field_origins, previous_revision_id)`. The current pointer is nullable while drafting. `revision_number` is unique per invoice. `InvoiceCurrentPeriod(invoice_id, meter_id, current_revision_id, local_daterange)` has one row per current confirmed invoice. A PostgreSQL exclusion constraint on meter and half open `local_daterange` prevents overlap. An invoice period starts and ends on the dates printed on the bill, inclusive, so one day is valid. No account number is copied into structured fields. Monetary values are Decimal with scale two; reject more precision instead of rounding input. `billed_kwh` is finite, nonnegative Decimal with at most six fractional places. A linked source document must belong to the same owner and meter.

**API surface**:

| Path and method | Input | Output | Key errors |
|---|---|---|---|
| `POST /meters/{id}/invoices` | Draft fields, field origins, optional retry key | Invoice and draft revision | 404 owner, 422 fields |
| `GET /meters/{id}/invoices` | Limit, cursor | Current items, next cursor | 404 owner |
| `GET /invoices/{id}` | Invoice ID | Current and prior revisions | 404 owner |
| `POST /invoices/{id}/revisions` | `base_revision_id` (the latest revision the client read, required), `expected_current_revision_id` (the confirmed pointer, null if never confirmed), changed fields, field origins, retry key | New draft revision with `changed_fields` and `old_values` relative to the base | 404 owner, 409 stale, 422 fields |
| `POST /invoices/{id}/confirm` | Draft revision ID, expected current revision, retry key | Confirmed revision | 409 stale or overlap, 422 missing or invalid |

All routes require the existing owner session. POST also requires CSRF. Error bodies use the existing problem format.

**Value sources**: Invoice values come from the submitted draft or a retained extraction proposal as changed by the owner. Distributor must match the meter's distributor unless the user explicitly records a documented discrepancy; a discrepancy blocks confirmation pending review. Actor and time come from the session and injected UTC clock. Currency is fixed to DOP and shown explicitly.

**Tests**: Database tests prove concurrent confirmation and correction cannot create two current revisions or overlapping current periods. Two concurrent edits of one draft produce one new revision and one 409. Verify a direct manual draft and correction, completing a partial never confirmed draft over two or more revisions and then confirming it, a stale `base_revision_id`, editing while a correction draft is open, partial draft, invalid dates or decimals, cross owner IDs, CSRF, retry replay, and audit metadata.

## Build plan

1. Add the invoice and revision migration, current period constraint, and owner scoped repository, satisfies **AC-1** to **AC-4**.
2. Add typed API and deterministic validation, then the minimal draft and confirm UI, satisfies **AC-1** to **AC-4**.
3. Run database concurrency and browser journey checks, satisfies **AC-2** to **AC-4**.

## Consequences

Immutable revisions use more rows, but a confirmed bill can be reconstructed and corrected without erasing the original decision.

## Rationale

The owner chose drafts, one meter per invoice, and versioned correction. This is the smallest model that keeps both a usable manual path and an honest confirmation trail.
