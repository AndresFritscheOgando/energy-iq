# Technology Stack and Version Policy

## Core
| Layer | Decision | Why / when |
|---|---|---|
| Language | Python 3.13 target, validate dependency compatibility before pin | Modern typing; reproducible runtime and dependency compatibility |
| Python tooling | `uv` for environment/package management; `ruff` for lint/format; `mypy` or `pyright` later | Repeatable, explicit engineering workflow |
| Tests | `pytest`, `hypothesis>=6.170` (dev only, locked at 6.170.14), `pytest-asyncio` where needed, coverage plugin | Simple unit + async test capabilities; Hypothesis property tests with shrinking for reading chain invariants ([spec 0006](specs/0006-reading-chain-property-tests/index.md)) |
| API | `fastapi>=0.162.0` (locked 0.162.0, with Starlette 1.10.0 and Pydantic 2.14.2), `uvicorn>=0.54.0` (locked 0.54.0), `pydantic-settings>=2.16.2` (locked 2.16.2); `httpx2>=2.16.0` dev only (locked 2.16.0) | Typed HTTP APIs, validation, `ENERGYIQ_*` settings; `httpx2` is the client Starlette 1.10 `TestClient` expects (plain `httpx` is deprecated there and leaves `TestClient` untyped). Upgrading FastAPI can change the committed OpenAPI snapshot ([spec 0008](specs/0008-minimal-fastapi-application/index.md)) |
| Database | PostgreSQL 18 in Compose (image `postgres:18.6-alpine`, loopback only), `sqlalchemy>=2.1.8` (locked 2.1.8, sync), `alembic>=1.20.1` (locked 1.20.1, with Mako 1.4.3), `psycopg[binary]>=3.3.7` (locked 3.3.7, binary wheels for Windows), `tzdata>=2026.6` (locked 2026.6, the IANA zone database Windows lacks) | Relational integrity, hand reviewed migrations, two roles (migrator owns schema, app gets column level grants per revision). Checked against PyPI and Docker Hub on 2026-11-04 for Python 3.13 ([spec 0009/0001](specs/0009-phase-two-persistence-auth/0001-database-foundation.md)) |
| Frontend | `frontend/`, pnpm 12.15.0, Node.js `>=24`, exact pins in `package.json` and `pnpm-lock.yaml`: `next` 16.4.5 (App Router, Turbopack, React Compiler on, Cache Components off), `react` and `react-dom` 19.3.0, `typescript` 5.9.3 (strict), `tailwindcss` and `@tailwindcss/turbopack` 4.3.4, shadcn 4.23.0 (`base-nova` style on `@base-ui/react` 1.9.0, with `cn` 0.5.2, `class-variance-authority` 0.7.1, `lucide-react` 1.67.0, `tw-animate-css` 1.4.0), `@tanstack/react-query` 5.105.3, `orval` 8.46.0 (dev), `react-hook-form` 7.91.0, `zod` 4.6.7, `@hookform/resolvers` 7.0.2, `server-only` 0.0.1. Dev checks: `eslint` 9.39.5 with `eslint-config-next` 16.4.5 and `eslint-plugin-jsx-a11y` 6.10.2, `prettier` 3.9.10, `vitest` 5.1.0 with `vite` 8.3.5 and `@vitejs/plugin-react` 6.2.1, `jsdom` 30.1.3, `@testing-library/react` 16.3.3, `@testing-library/dom` 10.4.1, `@testing-library/user-event` 14.6.8, `@testing-library/jest-dom` 7.0.1, `msw` 3.0.3, `axe-core` 4.14.0, `vitest-axe` 0.1.0, `@types/node` 24.19.2. Charting package selected in P3-03 | Typed client generated from the committed OpenAPI snapshot; versions checked on the npm registry on 2026-11-04 and tested together ([spec 0010](specs/0010-nextjs-foundation-session/index.md), [ADR-008](adr/ADR-008-frontend-data-access.md)) |
| Auth | Server sessions with a hashed opaque token in an HttpOnly `SameSite=Lax` cookie, a header plus `Origin` CSRF check, Argon2id through `argon2-cffi>=25.1.0` (locked 25.1.0, with `argon2-cffi-bindings` 26.1.0 and `cffi` 2.1.1; `CHEAPEST` profile in tests, `RFC_9106_LOW_MEMORY` elsewhere) | Avoid token storage in localStorage; revocable sessions. Checked on PyPI on 2026-11-04 for Python 3.13 ([spec 0009/0002](specs/0009-phase-two-persistence-auth/0002-identity-properties-meters.md)); see [ADR-007](adr/ADR-007-session-auth-same-origin-proxy.md) |
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

Spec 0011 pins: Recharts 3.10.1, `@playwright/test` 1.64.1, `@axe-core/playwright` 4.14.0.
