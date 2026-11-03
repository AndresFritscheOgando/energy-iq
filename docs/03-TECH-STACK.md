# Technology Stack and Version Policy

## Core
| Layer | Decision | Why / when |
|---|---|---|
| Language | Python 3.13 target, validate dependency compatibility before pin | Modern typing; reproducible runtime and dependency compatibility |
| Python tooling | `uv` for environment/package management; `ruff` for lint/format; `mypy` or `pyright` later | Repeatable, explicit engineering workflow |
| Tests | `pytest`, `hypothesis>=6.170` (dev only, locked at 6.170.14), `pytest-asyncio` where needed, coverage plugin | Simple unit + async test capabilities; Hypothesis property tests with shrinking for reading chain invariants ([spec 0006](specs/0006-reading-chain-property-tests/index.md)) |
| API | FastAPI + Pydantic v2 | Typed HTTP APIs, validation |
| Database | PostgreSQL (version pinned at implementation), SQLAlchemy 2.x, Alembic | Relational integrity, migrations |
| Frontend | Next.js with TypeScript, App Router; charting package selected at UI phase | Responsive full stack |
| Auth | Server-managed session with HttpOnly secure cookie (default proposal), CSRF strategy; ADR before implementation | Avoid token storage in localStorage |
| Local inference | Ollama + direct HTTP/official Python client behind `ModelProvider` | Local-first, replaceable |
| Vector search | PostgreSQL + pgvector, added only during RAG phase | Reuse Postgres and tenant-scope queries |
| Document processing | PDF native text extraction first; OCR/vision selectively benchmarked | Reduce hallucination and cost |
| Forecasting | `pandas`, `numpy`, `scikit-learn` baseline if justified; advanced libraries later | Compare simple methods before complex models |
| MCP | Official MCP Python SDK, version pinned when phase begins | Authenticated client and server tool integration |
| Runtime | Docker Compose locally; CI with GitHub Actions | Reproducibility |
| Observability | Structured JSON logs, OpenTelemetry traces and metrics where justified | Trace API + extraction + agent behavior |

## Version discipline
Before adding any package, consult official docs, test compatibility and **pin actual tested versions** into lockfiles. This specification intentionally does not fabricate package versions. For local models, store model name/tag, size, context constraints, hardware benchmark and digest if available. No universal 'best model' assumption.

## Ollama adapter requirements
- Interface methods (conceptual): `generate_structured`, `embed`, `health`, plus later `invoke_tools` for models that actually support it.
- Strict per-request timeout, max output, concurrency bound, cancellation, retry only for transient failures, observability with PII removed.
- Structured-output JSON schema + Pydantic validation; model-compliant shape does **not** imply correct values.
- Local-only network exposure; never expose Ollama's port publicly.
- Test with fake provider in unit tests; real model integration tests are opt-in and tagged.
- Benchmark small local text model and separate embedding model; image understanding requires explicit vision capability testing.
- Allow future hosted provider plug-in but disable external upload of personal bills by default.

## Hardware awareness
Aim for laptop development without large inference models; local Ollama may run on a more capable desktop. Avoid committing a 70B model requirement. CPU fallback permitted for small experiments. Record observed latency and RAM/VRAM to ground decisions.

## Official references
- FastAPI: https://fastapi.tiangolo.com/
- Python: https://docs.python.org/3/
- Pydantic: https://docs.pydantic.dev/
- SQLAlchemy: https://docs.sqlalchemy.org/
- Alembic: https://alembic.sqlalchemy.org/
- Ollama API: https://docs.ollama.com/api
- pgvector: https://github.com/pgvector/pgvector
- MCP Python SDK: https://py.sdk.modelcontextprotocol.io/
- Next.js: https://nextjs.org/docs
- OpenTelemetry: https://opentelemetry.io/docs/
- DGII reference (not utility tariff authority): https://dgii.gov.do/
