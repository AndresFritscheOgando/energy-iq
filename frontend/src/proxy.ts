import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

/**
 * Spec 0010 AC-18: decide what `X-Forwarded-For` may carry on its way to
 * FastAPI through the `/api` rewrite.
 *
 * Next.js never sets the header for a rewrite and passes a browser supplied
 * value through unchanged, so a browser could pick its own rate limit bucket.
 * `ENERGYIQ_EDGE_PROXY` (server only) decides:
 *
 * - exactly `true`: a trusted edge proxy appends the real peer address and is
 *   the only way to reach Next.js, so the header is left alone and FastAPI's
 *   rightmost untrusted rule picks the edge's entry.
 * - anything else: the header is deleted, FastAPI sees only the Next.js peer,
 *   and every browser shares one login and register bucket. Safe, but coarse.
 *
 * The value is read per request, not at build time, so one build serves both
 * topologies. `next.config.ts` makes `next build` and `next start` fail when
 * it is unset or invalid; this function never trusts anything but `true`.
 */
export function proxy(request: NextRequest): NextResponse {
  if (process.env.ENERGYIQ_EDGE_PROXY === "true") {
    return NextResponse.next();
  }
  const headers = new Headers(request.headers);
  headers.delete("x-forwarded-for");
  return NextResponse.next({ request: { headers } });
}

export const config = {
  matcher: "/api/:path*",
};
