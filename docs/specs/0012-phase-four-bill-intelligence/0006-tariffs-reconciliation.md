# 0006. Official tariffs and measured comparison

## Summary

Published SIE rules can support a narrow BTS-1 energy charge estimate. Reconciliation compares billed use with measured readings only when the meter history fully covers the bill period. It always separates invoice total from estimated energy charge.

## Requirements

- **AC-1**: A tariff draft names distributor, class, effective dates, SIE resolution and URL, source digest, publication and checking dates, exact bands, fixed charge, and rounding rule. Publication requires a human checked official source and nonoverlap with another published rule for the same scope.
- **AC-2**: Published rules are immutable. A new resolution creates a new version. The UI cites the applied resolution and dates. No default current rate or inferred class is allowed.
- **AC-3**: The first calculator accepts only a confirmed BTS-1 invoice for EDESUR, EDEESTE, or EDENORTE and one published rule that covers its entire billing period. It computes an exact Decimal energy charge from the invoice's billed kWh and cited bands, with source specified rounding. Unknown class, split rule period, or missing rate returns no estimate and a reason.
- **AC-4**: Reconciliation reports billed kWh, measured kWh, valid coverage and gaps for the inclusive local bill dates. Only complete valid coverage yields a numeric difference and mismatch conclusion. It never treats a partial interval or gap as zero or estimated use.
- **AC-5**: Invoice total, stated energy charge, estimated energy charge, taxes, fees, arrears, and other charges remain distinct. Tests use fixtures transcribed from checked SIE material and synthetic invoices, including boundaries and a missing source case.

## Decision

Publish a small validated tariff data model, not executable rules. Tariff authorship is an offline trusted maintenance operation, not a user or model route. Source PDFs and digests are retained as verification artifacts, but no real household bill is committed. Start with BTS-1 because the owner selected it. If the official SIE document cannot be checked, keep the schedule in draft and return no estimate.

## Feature design

**Schedule**: `TariffSchedule` contains distributor, `BTS-1`, inclusive effective dates, resolution ID, URL, source digest, checked actor and time, published state, and rounding policy. `TariffBand` contains ordered threshold and DOP per kWh as Decimal. Validate monotone bands, nonnegative values, and one unambiguous rule at any date. Source material must settle whether bands are marginal or whole block, whether a fixed charge applies, and whether a period crossing dates can be calculated. Until checked, the implementation must abstain. The first calculator abstains on any period crossing schedule versions.

**API surface**:

| Path and method | Input | Output | Key errors |
|---|---|---|---|
| `GET /meters/{id}/reconciliation` | Confirmed invoice ID | Billed and measured kWh, coverage, gaps, optional difference, optional estimate, source citation and reason codes | 404 owner, 409 unconfirmed |

Tariff maintenance uses a local command run with the migrator role, with a dry run and explicit publish action, not a public endpoint. A checked source manifest in version control names the reviewer, resolution, digest, and exact rule values. Code review and the migrator credential authorize publication. The command records a system audit row with the manifest revision and source digest, without private data.

**Window semantics**: Convert the bill's inclusive local start and end dates to a half open UTC window using the property's zone. Reuse the existing stored consumption service and its valid interval and gap rules. Since that service counts fully contained measured intervals, full coverage requires reading boundaries that align to the bill window. Display partial coverage rather than prorating a boundary interval. A zero measured value with full coverage is a true zero; missing coverage is not zero.

**Value sources**: Billed kWh and class come from the confirmed invoice. Measured kWh and gaps come from the stored meter reading chain. Rate and rounding come from one checked published SIE schedule. Invoice total and stated energy charge come from separate confirmed fields. Difference is exact subtraction only with full coverage.

**Tests**: Source transcribed BTS-1 band thresholds and rates with digest, exact threshold boundaries, zero kWh, rounding, no schedule, overlapping schedule rejection, wrong distributor, wrong class, split effective dates, partial coverage, invalid interval, and cross owner invoice IDs. Do not assert real rate values until the cited source has been read and checked.

## Build plan

1. Inspect the official SIE resolution and record applicability, exact tables, rounding, and source digest, satisfies **AC-1**, **AC-5**.
2. Add tariff migration, validation, and trusted maintenance command, satisfies **AC-1**, **AC-2**.
3. Add deterministic BTS-1 calculator and owner scoped reconciliation route, satisfies **AC-3** to **AC-5**.
4. Run source fixtures and live comparison tests, satisfies **AC-1** to **AC-5**.

## Consequences

The calculator abstains often, because it refuses to invent a class, split an unknown period, or infer missing usage. The result remains auditable and can widen when official rules and fixtures justify it.

## Rationale

The owner chose BTS-1 first and a mismatch conclusion only with complete measured coverage. The SIE index identifies resolution SIE-121-2026-TF for October to December 2026, but its index alone does not verify the tables or rounding. Those values must be checked in the resolution itself during this ticket.
