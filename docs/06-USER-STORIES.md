# User Stories and Acceptance Scenarios

Each story has a traceable ID. The implementation agent delivers one coherent story slice at a time, defining acceptance cases before implementing the feature and tests.

### US-001 — Compute usage from two observations (P0)
As a resident, I want to calculate consumed kWh between two readings so I understand usage.
- Given previous 13007 and current 13049, result is 42 kWh.
- Equal readings -> 0.
- Negative values -> validation error.
- Decreasing values without reset event -> error, not negative consumption.
- Unit test exact inputs and error type.

### US-002 — View reading history (P1)
As a resident, I want dated readings and intervals so I see a trend.
- Out-of-order submission does not corrupt chronological intervals.
- Duplicate timestamps are rejected or reconciled explicitly.
- A reset/replacement breaks continuity rather than showing impossible usage.
- Report intervals with duration and data coverage.

### US-003 — Manage properties and meters (P2)
As a user, I want separate properties and meters so I do not mix households.
- Creating a property returns owned resource.
- Users cannot enumerate, retrieve or mutate another user's property/meter.
- Each meter has a distributor and segment lifecycle.

### US-004 — See dashboard (P3)
As a user, I want a graph of usage with gap indicators so missing data is not mistaken for zero.
- Chart shows measurement windows and appropriate units.
- Empty, loading, error and partial-data UI states are accessible.

### US-005 — Record invoice manually (P4)
As a user, I want to enter my bill so I can compare billed and observed usage.
- Billing date range cannot be reversed.
- Billed kWh is stored separately from measured intervals.
- Total bill vs energy charge components are distinguishable.

### US-006 — Extract bill fields (P4)
As a user, I want proposed invoice fields from uploaded documents so I spend less time typing.
- Upload limited to supported file types/sizes; private storage.
- Proposed fields include per-field source, missing/uncertain flags.
- User can correct and confirm; audit retains before/after.
- Extraction failure cannot overwrite confirmed bills.

### US-007 — Compare distributor estimate (P4)
As a resident, I want an illustrative cost estimate based on versioned applicable rules.
- Rules have source and effective dates.
- Calculator explicitly distinguishes estimated charges from invoice total.
- Unknown customer tariff -> no fabricated estimate.

### US-008 — See anomalous use (P5)
As a resident, I want unusual intervals highlighted so I can investigate.
- Model uses historical-only data at inference time.
- Show baseline and why flagged; never assert root cause.
- Sparse data yields 'insufficient history' not a confident alert.

### US-009 — Forecast consumption (P5)
As a resident, I want a near-term trend forecast with uncertainty.
- Forecast carries horizon, training cutoff, method, error evidence.
- Backtest outperforms or is transparently compared with naive baseline.
- Forecast never displayed as actual usage.

### US-010 — Ask an energy question (P6)
As a user, I want an explanation of changes with cited evidence.
- Numeric statements reference verified computation or bill.
- Document claims cite accessible source/page.
- No relevant evidence => abstain or ask for more data.
- Cross-user bill fragments must be excluded.

### US-011 — Ask an agent to investigate (P7)
As a user, I want a bounded investigation over authorized data.
- Allowed tools, budgets, timeouts and log of calls.
- External instructions in invoices do not override policy.
- Write actions require explicit confirmation and idempotency.

### US-012 — Connect via MCP (P7)
As a developer, I want a secure MCP interface to retrieve my energy information.
- Tool schemas validated; owner identity from trusted context.
- Read-only tool results match HTTP-domain services.
- Unauthorized arguments fail without leaking records.

### US-013 — Reproduce production-style demo (P8)
As an interviewer, I want a documented, executable demo and objective metrics.
- Setup with seeded synthetic data and privacy-safe files.
- CI checks and unit/integration/evaluation instructions documented.
- Model and data limitations clearly stated.
