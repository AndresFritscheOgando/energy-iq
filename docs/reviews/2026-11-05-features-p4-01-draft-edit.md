# Review, features, 2026-11-05

**Reviewed by**: claude-opus-5-5 (author on sonnet)
**Scope**: 24 files (generated client excluded), uncommitted working tree vs HEAD
**Verdict**: Changes requested

## Summary
The change adds P4-01 manual invoices (migration `0004`, owner scoped repository, draft, confirm, and revision routes, meter page panel). The latest follow-up makes `POST /invoices/{id}/revisions` require `base_revision_id`, copy the latest revision whether draft or confirmed, and return 409 `stale_invoice_revision` for any other base. It also adds an Edit draft form. The backend is solid: the meter lock, then the invoice `FOR UPDATE` lock, then the latest revision check serializes edits correctly, the exclusion constraint backs up overlap, and the concurrency tests prove one 201 and one 409. The main problem is in the UI. After a stale 409 the open edit form keeps its stale base revision, so every retry fails again, even though the message tells the user to try again. The spec's audit metadata test is also missing.

## Major
### 🟠 The edit form stays pinned to a stale base after a 409, `frontend/src/components/invoices/InvoicePanel.tsx:147,193-195,367`
**Problem**: `editing.baseId` is captured when the form opens. On a 409 `onError` invalidates the list query, but `editing` and `editValues` are left as they were. The re-rendered form still submits `base_revision_id = editing.baseId`, which is no longer the latest, so the server returns 409 `stale_invoice_revision` every time. The changed-field diff (line 170) is also still computed against the old base. The user sees "The list was reloaded, so review the latest values and try again", but trying again from the open form can never succeed. They have to know to press Cancel and then Edit again. The test `explains a stale revision and reloads the list` (`frontend/tests/components/invoice-edit.test.tsx:105`) only checks the message and the refetch, so it misses this.
**Why it matters**: Stale writes are the exact case this follow-up was built for (two tabs, or a draft edited from another device). In that case the UI loops on 409.
**Suggested fix**: On `stale_invoice_revision`, close the form (`setEditing(null)`) or rebase it once the refetch finishes: set `baseId` to the new latest id and either reload `editValues` from it or keep the user's input and show what changed. Extend the Vitest case so a second submit after the 409 sends the new latest id.

### 🟠 No test checks invoice audit metadata, `backend/tests/db/test_invoices.py`
**Problem**: Spec 0012/0001 (Tests section, AC-4) requires verifying audit metadata with no private values. `test_concurrency.py` IDEMPOTENT entries only check that one `invoice.create`, `invoice.correct`, or `invoice.confirm` row exists on replay. Nothing asserts what `metadata` contains. Today the code writes only field names (`{"fields": [...]}`, plus `revision_id` on confirm), which is correct. But no test stops a later change from adding values such as `total_dop` or `old_values`.
**Why it matters**: AGENTS.md treats "audit without private values" as a hard rule, and the spec names this test explicitly. Other modules (`test_meters.py:43`, `test_properties.py:52`) do assert their metadata.
**Suggested fix**: Use `probe.audit(invoice_id)` in the journey test. Assert the exact `(action, metadata)` list for create, correct, and confirm, and assert that no numeric or date value from the request appears in the serialized metadata.

## Minor
### 🟡 Superseded drafts and replaced confirmations look live in history, `frontend/src/components/invoices/InvoicePanel.tsx:394-403`
**Problem**: A superseded draft keeps `status = "draft"` forever (by design), and a confirmation that a later one replaced keeps `"confirmed"`. History prints the raw status, so the e2e shows "Revision 1, draft" and "Revision 2, confirmed" next to "Revision 3, confirmed". Nothing says which revision is current or that revision 1 is superseded and cannot be confirmed.
**Why it matters**: Spec AC-3 wants the history to be honest, and a user could read this as an open draft or as two current bills.
**Suggested fix**: Work out the display state on the client: current if `id === current_revision_id`, superseded if it is not the latest and not current, otherwise the stored status. Or expose a derived `state` from `_revision_out`.

### 🟡 The UI cannot create the partial drafts that Edit draft is meant to complete, `frontend/src/components/invoices/InvoicePanel.tsx:274`
**Problem**: The New manual invoice form passes `required`, so the browser blocks saving without period, kWh, and total. AC-1 says "Drafts may be incomplete", and the new stepwise completion only matters for incomplete drafts. In the UI those can only arise from the API or from clearing fields in Edit draft.
**Suggested fix**: Drop `required` on the create form and leave completeness to the confirm step (422 `invoice_incomplete`, already mapped), or record why the create form deliberately requires these fields.

### 🟡 List does N+1 queries and returns unbounded history, `backend/src/energyiq/invoices/router.py:91-101,194`
**Problem**: `_invoice_out` runs one `revisions` query per invoice, up to `limit=500` per page, and returns every revision of every invoice. Payload size grows with the number of corrections.
**Suggested fix**: Load revisions for the page in one `WHERE invoice_id IN (...)` query and group them in Python. Consider returning only the latest and current revisions in the list, with full history from `GET /invoices/{id}`.

### 🟡 The API accepts no-op corrections, `backend/src/energyiq/invoices/router.py:240`
**Problem**: `changed` is `model_fields_set ∩ FIELDS`, so resubmitting the same value creates a new revision whose `changed_fields` names a field where `old_values` equals the new value. The UI filters these out, but direct API clients do not get the same guarantee. Formatting also matters: the UI compares `"100"` against `"100.000000"` as strings, so a retyped equal number counts as changed.
**Suggested fix**: Compare normalized values on the server (Decimal equality, date equality), drop unchanged fields, and return 422 `empty_correction` if nothing is left.

### 🟡 The invoice panel is shown for inactive meters, but writes return a generic error, `frontend/src/components/readings/MeterScreen.tsx:60-64`
**Problem**: Every invoice write calls `_meter(..., active=True)`, which returns 409 `meter_inactive`. `message()` has no mapping for that code, so the user sees "The invoice could not be saved. Try again." Readings are gated with `canAddReadings={active}`, but invoices are not.
**Suggested fix**: Pass `active` through and hide or disable the write controls, or map `meter_inactive` to a clear message.

## Nits
- ⚪ `backend/src/energyiq/invoices/router.py:343`, the inline `from psycopg.types.range import Range` inside a request handler; move it to module scope.
- ⚪ `backend/src/energyiq/invoices/router.py:232,308,331`, `assert` used for runtime invariants is stripped under `python -O`; use an explicit check or `typing.cast`.
- ⚪ `backend/src/energyiq/invoices/router.py:70`, `row.status if row.status == "draft" else "confirmed"` hides any unexpected value; the check constraint already guarantees the domain, so a `Literal` cast is clearer.
- ⚪ `frontend/src/components/invoices/InvoicePanel.tsx:294`, `const selected = latest;` is a leftover alias.
- ⚪ `frontend/src/components/invoices/InvoicePanel.tsx:173`, the `as unknown as Record<string, unknown>` cast; a typed key list (`keyof DraftCreate`) would keep the diff type-safe.

## Strengths
- Correct concurrency design: meter lock, then invoice `FOR UPDATE`, then a latest-revision check under the lock. `uq_invoice_revisions_number` and the GiST exclusion constraint act as database backstops, and `test_concurrent_edits_of_one_draft_create_one_revision` proves one 201 and one 409.
- Revisions are truly append-only. Column level grants allow only `status` and `confirmed_at` updates on `invoice_revisions`, so the immutability promise is enforced by PostgreSQL, not just by convention.
- Money and kWh are strict regex-validated strings turned into `Decimal`, with no rounding and scale-correct `Numeric` columns, as AGENTS.md requires.
- Ownership is enforced in `owned_invoices` through both `owner_id` and the property owner plus archive check, and the route-enumerated cross-user, CSRF, and idempotency suites were extended to the new routes.

## Test coverage
Backend: the journey, overlap and owner isolation, partial draft plus invalid values, stepwise completion over three revisions then confirm, stale `base_revision_id`, wrong pointer, missing base (422), editing while a correction draft is open, merged invalid period (422), and concurrent confirm, correct, and edit are all covered. I re-ran them: `tests/db/test_invoices.py` plus the invoice and idempotency cases of `test_concurrency.py` gave 11 passed. Gaps: there is no audit metadata assertion (Major above), no test that `meter_inactive` blocks edit and confirm, and no test for `distributor_discrepancy`. Frontend: `invoice-edit.test.tsx` gave 3 passed (re-run here). It covers sending only changed fields, the no-change guard, and the stale message plus refetch, but not recovery after a stale 409 (Major above). Playwright `invoices.e2e.ts` covers create, edit, confirm, correct, confirm, and history. PROGRESS.md correctly records that the full 57-case browser rerun after the final edit was not run.

## Resolution (2026-11-05, after the review)
- Fixed, major: the edit form now reloads on the newest revision after a stale 409, so the next save uses the new base. Vitest covers the 409 then a successful retry.
- Fixed, major: `test_audit_records_field_names_never_values` checks the create, correct, and confirm audit rows and that no entered value appears.
- Fixed, minor: history shows current, earlier confirmed, open draft, or superseded draft.
- Fixed, minor: the create form no longer requires the four core fields, so partial drafts can be made in the UI. A browser test completes one in steps and confirms it.
- Fixed, minor: the list loads all revisions for a page in one query (`revisions_by_invoice`). The list still returns full history per invoice, which is kept on purpose so the panel needs no second call.
- Fixed, minor: the API compares normalized values and drops unchanged fields, returning 422 `empty_correction` when nothing changed. The UI compares decimals numerically.
- Fixed, minor: the panel takes `active`; an inactive meter shows a read only note and no write controls, and `meter_inactive` has a clear message.
- Fixed, nits: `Range` import at module scope, explicit checks instead of `assert`, a typed status cast, the `selected` alias removed, and a typed key list in place of the `as unknown as Record` cast.
- Checks after the fixes: backend suite 992 passed, Ruff and Pyright clean, Vitest 439 passed, browser suite 58 passed, lint, typecheck, and format pass.
