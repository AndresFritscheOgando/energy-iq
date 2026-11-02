# Security, Privacy and Production Operations

## Threat model / trust boundaries
Untrusted: browser input, uploaded PDFs/images, OCR text, LLM outputs, retrieved chunks, MCP tool arguments, external documents. Trusted only after server-side validation and owner authorization. The model is **not** an authorization system.

## Top threats and controls
| Threat | Controls |
|---|---|
| Cross-property / cross-user data leak | Query scoping by authenticated owner; deny by default; IDOR tests; scoped retrieval and tools |
| Prompt injection in bill/manual | Treat document text as data; separate system/tool policy; restrict tool allowlist and arguments; adversarial evals |
| Malicious upload | File type magic validation, size/page limits, malware-scan option, storage isolation, no executable paths, PDF parser hardening |
| LLM hallucinated costs/tariffs | Numeric calculations only in verified deterministic service; evidence checks and abstention |
| Unsafe agent operations | Read-only by default; approval and strong authentication for consequential writes; audit every invocation |
| Credential exposure | Environment secrets; no secrets in git; rotate secrets; no PII in observability exports |
| Resource abuse / denial of service | Rate limits, quotas, concurrency, model timeout, cancellation, input/output limits |
| CSRF/XSS/session theft | HttpOnly Secure SameSite cookies, CSRF protection for cookie auth, CSP, escaping, session expiry |
| Data loss | Encrypted backups, documented restore drill, migration rollback plan |
| Untrusted model download | Verify publisher/licensing/model source, control artifacts, pin tags/digests where possible |

## Privacy / public portfolio guardrails
- Never publish real invoices, account numbers, utility client IDs, private household addresses, full GPS, or unredacted traces.
- Synthetic dataset by default; user-contributed samples require consent and de-identification.
- Local Ollama model operations preferred; if hosted model added, require explicit opt-in/data-handling notice.
- Provide export/delete flow and retention policy for files, embeddings, extracted text, logs, backup expiry.
- The repository's documentation is not legal advice; check Dominican privacy and data-handling requirements before actual external deployment.

## Observability requirements
- Structured request logs with correlation ID, route, status, duration; redact IP/account data as policy requires.
- Metrics: request throughput/errors/latency, database queries, background job age/retries, extraction failure rate, model tokens/latency/resource, RAG retrieval results, agent tool counts and safety denials.
- Distributed traces once async jobs/AI flows exist; do not record raw bills, full prompts or secrets by default.
- Dashboard and alert examples: high error rate, failed upload processing, runaway token usage, insufficient disk, backup failure.

## Local/deployed environment
- `dev`: synthetic data, debug logs only without PII, model health probe, migrations.
- `test`: isolated DB + fake model for deterministic CI.
- `prod-like`: TLS, secured cookies, private storage, secrets manager/environment injection, role-limited DB user, backups, no public Ollama.

## Runbooks to create in Phase 8
1. `RUNBOOK-DB-RESTORE`: stop writes, select backup, restore into test environment, verify referential integrity, resume.
2. `RUNBOOK-OLLAMA-DOWN`: reading/billing features stay available; AI endpoints return stable degraded response.
3. `RUNBOOK-EXTRACTION-FAILURE`: retry transient job, preserve original, expose review status, dead-letter after bound.
4. `RUNBOOK-INCIDENT`: triage alerts, collect redacted trace, rollback, communicate to affected users.

## Release checklist
- Migrations compatible and reversible or roll-forward plan documented.
- Auth/ownership negative tests passing.
- Data retention/privacy and upload hardening reviewed.
- Backups and restore procedure exercised.
- Model, prompt and evaluation revisions recorded.
- Accessibility and smoke tests complete.
- No unsafe autonomous actions or unverified 'current' rates in release.
