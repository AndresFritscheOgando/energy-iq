// @vitest-environment node
/**
 * Spec 0010 AC-18: `src/proxy.ts` decides what X-Forwarded-For may carry to
 * FastAPI. Only the exact text `true` keeps a supplied header.
 */
import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { config, proxy } from "../src/proxy";

const FORWARDED_BY_NEXT = "x-middleware-request-x-forwarded-for";
const OVERRIDE = "x-middleware-override-headers";

function request(headers: Record<string, string> = {}): NextRequest {
  return new NextRequest("http://localhost:3000/api/v1/auth/login", {
    method: "POST",
    headers,
  });
}

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("proxy", () => {
  it("false removes a supplied X-Forwarded-For", () => {
    vi.stubEnv("ENERGYIQ_EDGE_PROXY", "false");
    const response = proxy(request({ "x-forwarded-for": "6.6.6.6" }));

    expect(response.headers.get(OVERRIDE)).not.toBeNull();
    expect(response.headers.get(OVERRIDE)).not.toContain("x-forwarded-for");
  });

  it("false with no header leaves none", () => {
    vi.stubEnv("ENERGYIQ_EDGE_PROXY", "false");
    const response = proxy(request());

    expect(response.headers.get(FORWARDED_BY_NEXT)).toBeNull();
  });

  it("true keeps a supplied header untouched", () => {
    vi.stubEnv("ENERGYIQ_EDGE_PROXY", "true");
    const response = proxy(request({ "x-forwarded-for": "6.6.6.6, 198.51.100.7" }));

    // No override list at all: Next.js forwards the original request headers.
    expect(response.headers.get(OVERRIDE)).toBeNull();
    expect(response.headers.get(FORWARDED_BY_NEXT)).toBeNull();
  });

  it("true with no header changes nothing", () => {
    vi.stubEnv("ENERGYIQ_EDGE_PROXY", "true");
    const response = proxy(request());

    expect(response.headers.get(OVERRIDE)).toBeNull();
  });

  it.each([undefined, "", "TRUE", "1", "yes", "false"])(
    "treats %j as false, so a supplied header is removed",
    (value) => {
      if (value === undefined) {
        vi.stubEnv("ENERGYIQ_EDGE_PROXY", undefined);
      } else {
        vi.stubEnv("ENERGYIQ_EDGE_PROXY", value);
      }
      const response = proxy(request({ "x-forwarded-for": "6.6.6.6" }));

      expect(response.headers.get(OVERRIDE)).not.toContain("x-forwarded-for");
    },
  );

  it("never touches other request headers", () => {
    vi.stubEnv("ENERGYIQ_EDGE_PROXY", "false");
    const response = proxy(
      request({ "x-forwarded-for": "6.6.6.6", cookie: "a=b", origin: "http://localhost:3000" }),
    );

    expect(response.headers.get(OVERRIDE)).toContain("cookie");
    expect(response.headers.get(OVERRIDE)).toContain("origin");
  });
});

describe("matcher", () => {
  const matcher = new RegExp(`^${String(config.matcher).replace(":path*", ".*")}$`);

  it("covers the API paths and no page", () => {
    expect(config.matcher).toBe("/api/:path*");
    expect(matcher.test("/api/v1/auth/login")).toBe(true);
    expect(matcher.test("/login")).toBe(false);
    expect(matcher.test("/")).toBe(false);
  });
});
