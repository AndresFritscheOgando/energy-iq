// @vitest-environment node
/** `loadOrNotFound` and the prefetch timeout (spec 0011 umbrella). */
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import { getGetMeterQueryOptions } from "@/lib/api/generated/meters/meters";

import { problem } from "../msw/problems";
import { server } from "../msw/server";

vi.mock("server-only", () => ({}));
vi.mock("next/headers", () => ({
  cookies: async () => ({ get: () => undefined }),
}));

class NavigationSignal extends Error {}

vi.mock("next/navigation", () => ({
  redirect: (target: string) => {
    throw new NavigationSignal(`redirect ${target}`);
  },
  notFound: () => {
    throw new NavigationSignal("not found");
  },
}));

const { loadOrNotFound, serverRequestInit } = await import("@/lib/api/server");

const ID = "00000000-0000-4000-8000-000000000001";
const URL_ = `*/api/v1/meters/${ID}`;

async function load() {
  const init = await serverRequestInit();
  return loadOrNotFound(
    getGetMeterQueryOptions(ID, { request: { server: init } }),
    `/meters/${ID}`,
    { range: "30d" },
  );
}

describe("loadOrNotFound", () => {
  it("returns the data", async () => {
    server.use(http.get(URL_, () => HttpResponse.json({ id: ID })));
    await expect(load()).resolves.toEqual({ status: "ok", data: { id: ID } });
  });

  it.each([
    [404, "not_found"],
    [422, "validation_failed"],
  ])("calls notFound on a %i", async (status, code) => {
    server.use(http.get(URL_, () => problem(status, code)));
    await expect(load()).rejects.toThrow("not found");
  });

  it("redirects a lost session to login, keeping the query string", async () => {
    server.use(http.get(URL_, () => problem(401, "not_authenticated")));
    await expect(load()).rejects.toThrow(
      `redirect /login?next=${encodeURIComponent(`/meters/${ID}?range=30d`)}`,
    );
  });

  it("returns unavailable for an outage", async () => {
    server.use(http.get(URL_, () => problem(503, "database_unavailable")));
    await expect(load()).resolves.toEqual({ status: "unavailable", requestId: "req-123" });
  });

  it("throws anything else to error.tsx", async () => {
    server.use(http.get(URL_, () => problem(500, "internal_error")));
    await expect(load()).rejects.toThrow("500 internal_error");
  });
});
