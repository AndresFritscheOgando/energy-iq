// @vitest-environment node
/**
 * The meter page's server reads (spec 0011 child 0002 AC-1, AC-10; journey J7).
 * A failed or slow consumption call neither fails the page nor holds it up.
 */
import { http, HttpResponse } from "msw";
import { renderToString } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { en } from "@/messages/en";

import { problem, USER } from "../msw/problems";
import { server } from "../msw/server";

const state = vi.hoisted(() => ({ request: {} as object }));

vi.mock("server-only", () => ({}));
vi.mock("react", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react")>();
  return {
    ...actual,
    cache: <A extends unknown[], R>(fn: (...args: A) => R) => {
      const perRequest = new WeakMap<object, R>();
      return (...args: A): R => {
        if (!perRequest.has(state.request)) {
          perRequest.set(state.request, fn(...args));
        }
        return perRequest.get(state.request) as R;
      };
    },
  };
});
vi.mock("next/headers", () => ({ cookies: async () => ({ get: () => undefined }) }));

class NotFoundSignal extends Error {}
vi.mock("next/navigation", () => ({
  redirect: (target: string) => {
    throw new Error(`redirect ${target}`);
  },
  notFound: () => {
    throw new NotFoundSignal("not found");
  },
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn(), replace: vi.fn() }),
}));
vi.mock("next/dynamic", () => ({ default: () => () => null }));

const { default: MeterPage } = await import("@/app/(app)/meters/[meterId]/page");
const { QueryClientProvider, QueryClient } = await import("@tanstack/react-query");

const METER_ID = "00000000-0000-4000-8000-00000000000a";
const PROPERTY_ID = "00000000-0000-4000-8000-00000000000b";

function meter(extra = {}) {
  return {
    id: METER_ID,
    property_id: PROPERTY_ID,
    label: "Main meter",
    distributor: "EDESUR",
    active: true,
    ...extra,
  };
}

const PROPERTY = {
  id: PROPERTY_ID,
  nickname: "Demo home",
  region: null,
  timezone: "America/New_York",
};

function serve(consumption: () => Response | Promise<Response>) {
  server.use(
    http.get("*/api/v1/auth/me", () => HttpResponse.json(USER)),
    http.get(`*/api/v1/meters/${METER_ID}`, () => HttpResponse.json(meter())),
    http.get(`*/api/v1/properties/${PROPERTY_ID}`, () => HttpResponse.json(PROPERTY)),
    http.get(`*/api/v1/meters/${METER_ID}/readings`, () =>
      HttpResponse.json({ items: [], next_cursor: null }),
    ),
    http.get(`*/api/v1/meters/${METER_ID}/consumption`, consumption),
  );
}

async function page(query: Record<string, string> = {}) {
  const element = await MeterPage({
    params: Promise.resolve({ meterId: METER_ID }),
    searchParams: Promise.resolve(query),
  } as never);
  return renderToString(
    <QueryClientProvider client={new QueryClient()}>{element}</QueryClientProvider>,
  );
}

beforeEach(() => {
  state.request = {};
});

describe("the meter page", () => {
  it("still renders the form and list when consumption fails", async () => {
    serve(() => problem(500, "internal_error"));
    const html = await page();
    expect(html).toContain("Main meter");
    expect(html).toContain(en.readingForm.title);
    expect(html).toContain(en.usage.loading);
  });

  it("doesn't wait more than the prefetch timeout for a slow chart", async () => {
    serve(() => new Promise(() => undefined));
    const started = Date.now();
    const html = await page();
    expect(Date.now() - started).toBeLessThan(4000);
    expect(html).toContain(en.usage.loading);
  }, 10_000);

  it("computes the window once on the server, in the property's zone", async () => {
    let params: URLSearchParams | null = null;
    serve(() => HttpResponse.json({}));
    server.use(
      http.get(`*/api/v1/meters/${METER_ID}/consumption`, ({ request }) => {
        params = new URL(request.url).searchParams;
        return problem(500, "internal_error");
      }),
    );
    await page({ range: "30d" });
    const from = Date.parse(params!.get("from") as string);
    const to = Date.parse(params!.get("to") as string);
    const days = (to - from) / 86_400_000;
    expect(Math.round(days)).toBe(30);
    expect(to).toBeGreaterThan(Date.now());
    // New York midnight is 04:00Z or 05:00Z.
    expect(["04", "05"]).toContain(params!.get("to")!.slice(11, 13));
  });

  it("shows not found for an unknown meter", async () => {
    serve(() => HttpResponse.json({}));
    server.use(http.get(`*/api/v1/meters/${METER_ID}`, () => problem(404, "not_found")));
    await expect(page()).rejects.toBeInstanceOf(NotFoundSignal);
  });

  it("shows the unavailable panel when the meter can't load", async () => {
    serve(() => HttpResponse.json({}));
    server.use(http.get(`*/api/v1/meters/${METER_ID}`, () => problem(503, "database_unavailable")));
    expect(await page()).toContain(en.unavailable.message.replace("'", "&#x27;"));
  });
});
