# 0005. Invoice review and provenance screens

## Summary

The invoice page shows what the system found, where it found it, and what you changed. Confirmation is a separate action. The screens extend the existing Phase 3 design in `docs/screen-references/`.

## Requirements

- **AC-1**: A meter page lists current invoices and their state, with a manual entry action and an upload action. Lists paginate and have empty, loading, error, and retry states.
- **AC-2**: The review screen shows a private source preview or download, page reference, proposed value, confidence or uncertainty wording, and edited value for every field. A field without source evidence is labelled as such.
- **AC-3**: Conflict and arithmetic messages name the affected fields without inventing a value. The owner can save a draft even when required fields are absent, but confirmation lists each missing or invalid field.
- **AC-4**: The explicit confirm action sends the draft revision ID and expected current revision. A stale or overlapping response leaves edits visible and asks the owner to resolve the conflict. It never silently retries a different revision.
- **AC-5**: Keyboard focus, labels, errors, status announcements, mobile layout, and light and dark contrast are verified in a browser. The page never embeds an untrusted PDF inline with app origin privileges.

## Decision

Extend the existing nested meter routes and Phase 3 screen tokens. Use a side by side source and form layout on wide screens, stacked panels on narrow screens. The source opens as an authorized attachment or a safely rendered page image under a separate origin if a preview is implemented; the minimum build offers download plus page text evidence. The review form keeps a local unsaved edit state and submits only through the generated typed client.

## Feature design

**Routes**: `/meters/[meterId]/invoices`, `/meters/[meterId]/invoices/new`, and `/invoices/[invoiceId]`. The document status and run evidence are fetched through the owner scoped API. The page shows source type `manual` or `document`, revision author and UTC time formatted for the property time zone, and the source page for each candidate. It never shows storage keys or model prompts.

**Value sources**: Invoice list fields come from current revisions. Proposed values and page quotes come from the extraction run and field evidence. Corrected values come from the draft revision. Timestamp display uses the property time zone, default `America/Santo_Domingo`. Tariff estimates come only from the reconciliation response, never client math.

**Tests**: Vitest checks form states and stale response preservation. Playwright checks a synthetic manual path, upload review, correction, source download authorization, keyboard flow, axe in light and dark, and a model failure that still permits manual entry.

## Build plan

1. Generate the API client and build the list and manual form on existing tokens, satisfies **AC-1**, **AC-3**.
2. Build review evidence, corrections, and explicit confirmation, satisfies **AC-2** to **AC-4**.
3. Run live browser and accessibility checks, satisfies **AC-5**.

## Consequences

The minimum review uses page text and a source download rather than a trusted inline PDF viewer. This avoids giving an untrusted document the app origin.

## Rationale

The owner chose the Phase 3 design handoff as the visual source. The UI keeps source and correction together so a reviewer can inspect a proposal before confirming it.
