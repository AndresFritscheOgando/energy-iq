# Testing and AI Evaluation Strategy

## Pyramid
- **Unit:** consumption, readings sorting, reset semantics, decimal money, tariff calculations, permissions logic, prompt/output validators. Fast, pure, no model or DB.
- **Integration:** PostgreSQL migrations, repositories, upload processing, local stub Ollama, pgvector tenant filtering.
- **Contract:** Pydantic/OpenAPI compatibility, frontend API client, MCP schemas, provider adapters.
- **End-to-end:** sign in -> property/meter -> reading -> graph -> bill upload/confirm -> grounded Q&A with synthetic fixtures.
- **Security:** tenant leaks, malformed uploads, prompt injection, unauthorized tool arguments, replay, rate limits.
- **Operational:** backup/restore, model unavailable, database outage, slow inference, queue retries and resource exhaustion.

## Deterministic acceptance matrix
- 13007 -> 13049 = 42 kWh; 12964 -> 12979 = 15 kWh.
- equal readings = zero.
- previous > current without event -> invalid.
- negative, NaN, infinite, non-numeric input -> rejected.
- Direct consumption calls reject integer, float, bool, string, and None inputs with TypeError; nonfinite Decimal values raise ValueError before comparison.
- Exact subtraction or explicit arithmetic failure under the documented precision 28 policy; verify caller precision, rounding, exponent limits, traps, and flags do not affect results or change after a call.
- Unsupported timestamp types and malformed observation pairs raise clear errors, while stable ordering, duplicates, and input preservation remain intact.
- same timestamp and leap/daylight/timezone handling explicit (Dominican Republic timezone currently no DST).
- meter replacement/reset yields segment break and no spurious negative interval.
- no interpolating missing data into factual consumption.
- mixed property or partially overlapping intervals not double-counted.

## Property based tests (P1-05)
`backend/tests/test_reading_properties.py` generates reading chains, events, windows, and cut points and runs them through the real `order_readings`, `compute_intervals`, and `summarize_consumption` code ([spec 0006](specs/0006-reading-chain-property-tests/index.md)). It checks ordering stability and conflict groups, the spec 0004 interval rules, exact window tiling (no hole, no overlap, exact kWh, single half even rounding, no floats), and additivity over 2 to 5 adjacent windows. Generators use a coarse time grid so collisions, 1 µs intervals, events on reading instants, and window bounds on or 1 µs from interval boundaries come up regularly.

Profiles live in `backend/tests/conftest.py` and are chosen by `ENERGYIQ_HYPOTHESIS_PROFILE`:
- `energyiq` (default): 200 examples per property, derandomized, no example database, no deadline, failure blob printed. Every run tries the same examples, so a red run means a code change (or a Hypothesis upgrade).
- `deep` (opt in): 2000 random examples per property and the local example database in `.hypothesis/` (git ignored). Run with `ENERGYIQ_HYPOTHESIS_PROFILE=deep uv run pytest backend/tests/test_reading_properties.py`.

Both profiles inherit from Hypothesis's built in default, so its automatic `ci` profile never changes local or CI behavior. An unknown profile name stops the session. No health check is suppressed. If a property finds a defect, pin the shrunk case as an `@example` and as a plain unit test in the matching test file.

## Bill extraction evaluations (Phase 4)
Create a versioned labeled corpus of synthetic or authorized anonymized sample invoices; vary issuer/layout/scan quality/orientation/partial fields. Ground truth includes supplier, bill period, billed kWh, amount DOP, energy charge, other fees and field evidence. Metrics: field-level exact match/normalized accuracy, missing-field rate, false field rate, correction rate, document-level 'all required correct', processing latency, local memory cost. Split by layout to detect template overfitting. Save failure examples with redaction.

## Forecast / anomaly evaluation (Phase 5)
- Establish naive last-period and seasonal naive baselines before ML.
- Use chronological training/validation/test and rolling-origin backtesting; never random-shuffle time series.
- MAE and WAPE where appropriate; note MAPE division issues near zero, plus prediction interval coverage.
- Monitor coverage/gaps, meter events, seasonal drift and high-impact outliers.
- For anomalies track precision/recall on curated incidents, alerts per month, false-positive review effort.
- Report weak baselines and limitations instead of declaring the AI accurate.

## RAG evaluation (Phase 6)
Build 40+ synthetic or permissioned question/evidence pairs: exact bills, ambiguous terms, missing data, cross-property questions, mismatched billing vs meter periods, prompt injection in uploaded text. Metrics: retrieval recall@k, citation precision/support, factual error rate, abstention correctness, answer completeness, latency/token counts. Use **independent deterministic verification** for numeric results; LLM judges are supplementary, not sole truth source.

## Tool/agent/MCP evaluations (Phase 7)
- Valid authorized tool calls succeed; mismatched property ID fails.
- Malicious prompt in PDF asks model to fetch a different account -> blocked.
- Repeated write action does not duplicate effect; approval required.
- Enforce tool-call count, timeout, cancellation, output size, auth propagation, audit trace.
- Assess task success, unsafe-action attempts blocked, tool error recovery and cost.

## CI quality gates
Phase 0: formatting + unit tests. Phase 2+: lint + static typing + migration/integration suite. Phase 4+: extraction regression datasets on explicit/opt-in runner; real local-model tests separated from CI deterministic suite. Phase 6+: RAG golden eval threshold established from baseline. Phase 8: security scanning and end-to-end smoke tests. If empirical thresholds are unknown, mark `TBD until baseline` and document collected results rather than inventing targets.

## Reporting template
| Dataset/version | Model/tag | Prompt revision | Metric | Baseline | Current | Decision | Known failure cases |
|---|---|---|---|---|---|---|---|
Use `not run` rather than estimated figures. Capture tool and model reproducibility details.
