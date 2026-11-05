# 0012. Rationale

## Context

Phase 3 supplies owner scoped meters, readings, consumption, and a browser UI. Phase 4 adds sensitive source documents, model suggestions, and dated public tariffs. A wrong field or rate could make a household comparison look authoritative when it is not. Phase 3 spec 0011 still awaits a fresh review, so this design does not close that gate.

## Options considered

**Invoice lifecycle**: Draft, explicit confirmation, and immutable revisions (chosen) keep a recoverable trail at the cost of extra rows and conflict handling. Direct confirmed writes are faster but make source disagreements hard to review. Editing one current row with an audit log is smaller initially but makes historical values harder to reconstruct.

**Storage and processing**: Private local files plus database leased runs (chosen) need no new service, but require file reconciliation and durable backups. PostgreSQL large objects simplify transaction boundaries but enlarge database backups and complicate file limits. Object storage and a broker suit several hosts but add infrastructure before this repository needs it.

**PDF parsing**: Native text first with manual review for scans (chosen) has clear evidence and low local resource cost, but scans need typing. Immediate OCR or vision could cover more files, but its quality and hardware cost are not yet measured on this product's layouts.

**Model boundary**: Local Ollama structured output with an independent validator (chosen) helps entry without giving the model authority. Regex only is simpler and deterministic but brittle across layouts. A hosted model might improve extraction, but would move private bills outside the local boundary and needs separate consent and data handling work.

**Tariff scope**: Verified BTS-1 rules with abstention (chosen) make the first estimate narrow. Supporting every regulated class would require demand, time, and other charge semantics before fixtures exist. Showing a current price from a web result would be quick but could misstate the rule and date.

## Rationale

The design follows the existing trust split: calculations and ownership remain in deterministic services, while the model offers a reviewable suggestion. The owner chose one meter per invoice, drafts before confirmation, retained source files until owner deletion, versioned corrections, manual review for scans until evaluation, and manual entry during model failures. The owner also chose BTS-1 first and to withhold a kWh mismatch when coverage is incomplete. These choices keep every display value tied to an input, a reading, a person, or a checked rule.

The existing 1 MiB JSON body cap cannot simply be raised for PDF upload. A separate bounded multipart path is needed. A local worker using database leases keeps the request path short and makes crashes visible without a broker. `pypdf` can extract native text by page, and its own guide explains why it cannot extract words from an image. Source page and exact quote are the first evidence contract; geometry remains optional.

## References

**Project sources**: `AGENTS.md`, `docs/01-PRD.md`, `docs/04-DATA-MODEL-API.md`, `docs/05-IMPLEMENTATION-ROADMAP.md`, `docs/06-USER-STORIES.md`, `docs/07-TESTING-EVALUATIONS.md`, `docs/08-SECURITY-OPERATIONS.md`, `docs/10-AI-DESIGN.md`, `docs/11-DECISIONS-OPEN-QUESTIONS.md`, specs 0009, 0010, and 0011, ADR-003, and ADR-007.

**Practices and standards**: exact Decimal money, independent validation of model output, owner scoped queries, private file storage, explicit human confirmation, and effective dated rules.

**Links checked on 2026-11-05**:

- [SIE resolutions index](https://sie.gob.do/transparencia/base-legal-de-la-institucion/resoluciones-sie/) lists SIE-121-2026-TF for October to December 2026. The index is not a verified rate table.
- [SIE tariff classes](https://sie.gob.do/categorias-faqs/tarifas-y-facturacion/) identifies BTS-1 among regulated classes.
- [Ollama structured output guide](https://ollama.com/blog/structured-outputs) documents JSON schema output.
- [pypdf text extraction guide](https://pypdf.readthedocs.io/en/stable/user/extract-text.html) documents native text and image limitations.
- [OWASP file upload guidance](https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html) covers content validation, size limits, private storage, and CSRF.

## Evidence limits

The SIE resolution index was checked, but its PDF tables were not transcribed or verified. No real tariff amount belongs in the design or tests until child 0006 records the exact source. `pypdf` and Ollama package versions, a model digest, machine latency, resource limits, and an OCR or vision choice are not yet tested. Each is an implementation gate in its child, not a claim of completed behavior.
