# EnergyIQ web app

The Next.js browser app for EnergyIQ. See the root [README](../README.md) ("Run the web app") for local setup, [spec 0010](../docs/specs/0010-nextjs-foundation-session/index.md) for the design, and [ADR-008](../docs/adr/ADR-008-frontend-data-access.md) for the data access rules.

| Script                      | What it does                                                          |
| --------------------------- | --------------------------------------------------------------------- |
| `pnpm dev`                  | Dev server on `http://localhost:3000`                                 |
| `pnpm build` / `pnpm start` | Production build and server; both need `ENERGYIQ_API_ORIGIN`          |
| `pnpm lint`                 | ESLint (Next.js core web vitals, jsx-a11y), zero warnings             |
| `pnpm typecheck`            | Route type generation, then `tsc --noEmit`                            |
| `pnpm test`                 | Vitest once (MSW, Testing Library, axe, codegen drift)                |
| `pnpm format:check`         | Prettier check                                                        |
| `pnpm gen:api`              | Regenerate `src/lib/api/generated/` from the backend OpenAPI snapshot |

Rules every screen follows:

- Call the API only through the generated client; `src/lib/api/fetcher.ts` is the only `fetch` caller.
- Every page in `src/app/(app)/` starts with `await requireSession(path, await searchParams)`.
- Server reads go through `getServerQueryClient()` and `serverRequestInit()` from `src/lib/api/server.ts`.
- User facing text lives in `src/messages/en.ts`; dates go through `formatDateTime`.
- kWh and money values stay strings; never convert them with `Number`.
