import type { NextConfig } from "next";
import { PHASE_PRODUCTION_BUILD, PHASE_PRODUCTION_SERVER } from "next/constants";

/**
 * Spec 0010 AC-2 and AC-13.
 *
 * The `/api` rewrite is the same origin proxy from ADR-007: the browser only
 * talks to Next.js, which forwards `/api/*` to FastAPI. Next.js writes the
 * rewrite destination into the routes manifest when `next build` runs, so the
 * same `ENERGYIQ_API_ORIGIN` must be set at build and at `next start`.
 *
 * `ENERGYIQ_API_ORIGIN` is read only here and in `src/lib/api/server.ts`.
 * It is never a `NEXT_PUBLIC_` variable, so it never reaches the browser.
 */
const DEV_API_ORIGIN = "http://127.0.0.1:8000";

/** `next build` and `next start`; dev and tooling use the default. */
const PRODUCTION_PHASES = new Set([PHASE_PRODUCTION_BUILD, PHASE_PRODUCTION_SERVER]);
// `next typegen` (run by `pnpm typecheck`) loads this file in the build phase
// but never serves or builds anything, so it does not need the origin.
const IS_TYPEGEN = process.argv.includes("typegen");

function apiOrigin(phase: string): string {
  const value = process.env.ENERGYIQ_API_ORIGIN?.trim();
  if (value) {
    return value.replace(/\/+$/, "");
  }
  if (PRODUCTION_PHASES.has(phase) && !IS_TYPEGEN) {
    throw new Error(
      "ENERGYIQ_API_ORIGIN is not set. Set it to the FastAPI origin " +
        "(for example http://127.0.0.1:8000) for both `next build` and `next start`.",
    );
  }
  return DEV_API_ORIGIN;
}

/**
 * Spec 0010 AC-18. `src/proxy.ts` reads `ENERGYIQ_EDGE_PROXY` per request and
 * treats anything but exactly `true` as `false`. Here we only refuse to build
 * or start in production without an explicit `true` or `false`, so a deploy
 * cannot choose by accident.
 */
function checkEdgeProxy(phase: string): void {
  const value = process.env.ENERGYIQ_EDGE_PROXY;
  if (PRODUCTION_PHASES.has(phase) && !IS_TYPEGEN && value !== "true" && value !== "false") {
    throw new Error(
      "ENERGYIQ_EDGE_PROXY must be exactly `true` or `false` for `next build` and " +
        "`next start`. Use `true` only behind a trusted edge proxy that appends the " +
        "real client address to X-Forwarded-For and is the only way to reach Next.js.",
    );
  }
}

const securityHeaders = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Content-Security-Policy", value: "frame-ancestors 'none'" },
  {
    key: "Permissions-Policy",
    value: "camera=(), microphone=(), geolocation=()",
  },
];

const nextConfig = (phase: string): NextConfig => {
  checkEdgeProxy(phase);
  return buildConfig(phase);
};

const buildConfig = (phase: string): NextConfig => ({
  poweredByHeader: false,
  // Spec 0010 AC-12: the dev CSRF message is shown to a tester who opened
  // 127.0.0.1. Without this, Next.js blocks its dev resources for that host,
  // the page never hydrates, and the form falls back to a native submit.
  allowedDevOrigins: ["127.0.0.1"],
  reactCompiler: true,
  // Spec 0010 AC-18: rewrites match paths ignoring letter case by default, but
  // the `proxy.ts` matcher is case sensitive, so `/API/...` would reach FastAPI
  // with the browser's X-Forwarded-For untouched. Case sensitive routes make
  // both agree: `/API/...` is simply not found.
  experimental: { caseSensitiveRoutes: true },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${apiOrigin(phase)}/api/:path*`,
      },
    ];
  },
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
});

export default nextConfig;
