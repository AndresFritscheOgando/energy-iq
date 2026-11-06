# Review, features, 2026-11-05

**Reviewed by**: claude-opus-5-5 (author on a different model)
**Scope**: 4 files, uncommitted (diff against HEAD 565ff17)
**Verdict**: Approve with nits

## Summary
`frontend/src/proxy.ts` now deletes a browser supplied `X-Forwarded-Proto` alongside `X-Forwarded-For` unless `ENERGYIQ_EDGE_PROXY` is exactly `true`. The backend docstring is corrected, and tests on both sides cover the new behavior. The code change is one line, correct, and fails safe. I checked it against the installed Next.js 16.4.5: the rewrite proxy (`proxy-request.js`, httpxy without `xfwd`) sets only `x-forwarded-host` and never `x-forwarded-proto`, so nothing re-adds the header after `proxy.ts` deletes it. The remaining issues are about docs and the tripwire. README, ADR-008, spec 0010 AC-18, and PROGRESS still describe only `X-Forwarded-For`, and two PROGRESS rows now state the opposite of the new behavior. The rerunnable live check does not probe the new header.

Context on impact: because the rewrite uses `changeOrigin: true`, FastAPI sees `Host` as the backend host. That means a spoofed scheme could only turn the CSRF own origin into `https://127.0.0.1:8000`, which no real browser origin matches. The fix is sound defense in depth rather than the closing of a live exploit, and that matches the minor severity the previous review gave it.

## Minor

### 🟡 Docs and progress log contradict the new behavior, `docs/PROGRESS.md:12-13`, `README.md:91`, `docs/adr/ADR-008-frontend-data-access.md:15`, `docs/specs/0010-nextjs-foundation-session/index.md:37-39,143`
**Problem**: PROGRESS row 12 says the docstring "states ... that a browser `X-Forwarded-Proto` reaches FastAPI from the trusted peer". Row 13 lists "`proxy.ts` still does not strip a browser `X-Forwarded-Proto`" as an open minor. Both are now false, and no new dated row records this change or the checks run (the pytest parametrization, the two vitest cases, and the live `next start` check for both flag values). README, ADR-008, the AC-18 bullets, and the Configuration entry for `ENERGYIQ_EDGE_PROXY` all say `false` deletes only `X-Forwarded-For`.
**Why it matters**: AGENTS.md requires PROGRESS to be truthful and impacted docs and ADRs to be updated. Someone reading the spec or the ADR to decide P8 edge configuration would not learn that the scheme header is also gated by the flag.
**Suggested fix**: Add a dated PROGRESS row with the observed checks, and mark the row 13 open minor as closed. Update the README paragraph, ADR-008, AC-18 (`false` deletes both headers; `true` leaves both), and the Configuration line for `ENERGYIQ_EDGE_PROXY`.

### 🟡 `true` topology contract does not say the edge must overwrite `X-Forwarded-Proto`, `frontend/src/proxy.ts:13-15` (and README/ADR-008/spec)
**Problem**: The docstring says the edge "sets the scheme", but the documented contract for `true` (README, ADR-008, spec line 143, the P8 follow up at line 211) only requires the edge to append the real peer to `X-Forwarded-For`. With `true`, a browser's `X-Forwarded-Proto` passes through untouched. It is only safe if the edge replaces the header rather than passing it through or appending. If the edge appends, Uvicorn ignores the comma list and the scheme falls back to `http`.
**Why it matters**: A P8 edge configured to the written contract could forward a browser chosen scheme from the trusted loopback peer. That is the exact case this change closes for `false`.
**Suggested fix**: Add to the `true` requirements in README, ADR-008, spec AC-18, and the P8 follow up: "the edge sets (overwrites) `X-Forwarded-Proto` to the scheme the browser used."

### 🟡 Live check tripwire does not cover `X-Forwarded-Proto`, `frontend/scripts/check-edge-proxy.mjs:25-27,85-92`
**Problem**: The echo server records and probes only `x-forwarded-for`. The intent says a live `next start` check confirmed the proto behavior for both flag values, but it is not in the rerunnable script. ADR-008 calls that script "the tripwire if a later Next.js release changes this behavior".
**Why it matters**: A future Next.js change to how rewrites or proxy request overrides treat `x-forwarded-proto` would pass unit tests, which only exercise `NextResponse.next` header encoding. It would go unnoticed until someone re-checks by hand.
**Suggested fix**: Echo `x-forwarded-proto` too. Add a spoofed `https` probe that must arrive as none with `false` and as sent with `true`.

## Nits
- ⚪ `frontend/tests/proxy.test.ts:3-4`: file docstring still says the proxy decides what "X-Forwarded-For may carry"; it should mention both headers.
- ⚪ `frontend/tests/proxy.test.ts:57-69`: the falsy-value matrix (`undefined`, `""`, `TRUE`, `1`, `yes`) only asserts `x-forwarded-for` removal. Sending both headers in that case would pin the proto behavior to the same matrix at no cost.
- ⚪ `frontend/src/proxy.ts:6`: "may carry on its way" should read "on their way" now that it covers two headers.

## Strengths
- The change is minimal and fails safe: proto stripping sits on the same `!== "true"` path as `X-Forwarded-For`, so every non-`true` value, including unset, strips both.
- The backend test now parametrizes all four schemes Uvicorn accepts (`https`, `http`, `ws`, `wss`), which pins the docstring's claim. The corrected `ForwardedClientMiddleware` docstring now matches reality.
- The frontend `false` test checks both that the header is absent from the override list and that no `x-middleware-request-x-forwarded-proto` value is emitted. That is the actual Next.js encoding contract, not a mock.

## Test coverage
New behavior is covered: `false` strips a supplied proto, and `true` leaves the request untouched, with no override list. Backend trust of a single valid proto from a trusted peer is covered for all four accepted values, alongside the existing junk, untrusted peer, and CSRF origin tests. Ran locally: `uv run pytest tests/api/test_proxy_headers.py`, 19 passed; `pnpm vitest run tests/proxy.test.ts`, 14 passed. Gaps: the falsy-value matrix does not include proto (nit), and the end to end tripwire script does not exercise proto (minor above). The full backend and frontend suites were not run by the reviewer.
