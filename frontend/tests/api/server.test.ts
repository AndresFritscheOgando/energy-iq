// @vitest-environment node
/**
 * Server reads and the session guard (spec 0010 AC-5, AC-6).
 *
 * Outside a React Server Component render `React.cache` does not memoize,
 * so `react` is mocked with a `cache` scoped to a simulated request: each
 * test sets `request` to a new object to start "another request".
 */
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { problem, USER } from "../msw/problems";
import { server } from "../msw/server";

const state = vi.hoisted(() => ({
  request: {} as object,
  cookies: new Map<string, string>(),
}));

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

vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: (name: string) =>
      state.cookies.has(name) ? { name, value: state.cookies.get(name) } : undefined,
  }),
}));

class RedirectSignal extends Error {
  constructor(readonly target: string) {
    super(`NEXT_REDIRECT ${target}`);
  }
}

vi.mock("next/navigation", () => ({
  redirect: (target: string) => {
    throw new RedirectSignal(target);
  },
}));

const {
  getServerQueryClient,
  loginRedirectTarget,
  redirectIfSignedIn,
  requireSession,
  serverRequestInit,
} = await import("@/lib/api/server");

const ME = "http://127.0.0.1:8000/api/v1/auth/me";

function newRequest(cookies: Record<string, string> = {}) {
  state.request = {};
  state.cookies = new Map(Object.entries(cookies));
}

function countMe(respond: () => Response) {
  const calls: Request[] = [];
  server.use(
    http.get(ME, ({ request }) => {
      calls.push(request);
      return respond();
    }),
  );
  return calls;
}

beforeEach(() => {
  vi.stubEnv("ENERGYIQ_API_ORIGIN", "");
  newRequest();
});

describe("serverRequestInit", () => {
  it("forwards only the two session cookies and sets no-store", async () => {
    newRequest({
      energyiq_session: "plain",
      "__Host-energyiq_session": "secure",
      analytics: "do-not-forward",
    });

    await expect(serverRequestInit()).resolves.toEqual({
      baseUrl: "http://127.0.0.1:8000",
      cookie: "energyiq_session=plain; __Host-energyiq_session=secure",
      cache: "no-store",
    });
  });

  it("sends no cookie when there is no session", async () => {
    newRequest({ analytics: "x" });

    expect((await serverRequestInit()).cookie).toBe("");
  });

  it("reads ENERGYIQ_API_ORIGIN at runtime", async () => {
    vi.stubEnv("ENERGYIQ_API_ORIGIN", "http://fastapi.internal:9000/");

    expect((await serverRequestInit()).baseUrl).toBe("http://fastapi.internal:9000");
  });
});

describe("getServerQueryClient", () => {
  it("is one client per request and never shared across requests", () => {
    newRequest();
    const first = getServerQueryClient();
    expect(getServerQueryClient()).toBe(first);

    newRequest();
    expect(getServerQueryClient()).not.toBe(first);
  });
});

describe("requireSession", () => {
  it("returns the user and makes one /auth/me call per request", async () => {
    newRequest({ energyiq_session: "token" });
    const calls = countMe(() => HttpResponse.json(USER));

    const first = await requireSession("/");
    const second = await requireSession("/");

    expect(first).toEqual({ status: "signed_in", user: USER });
    expect(second).toEqual(first);
    expect(calls).toHaveLength(1);
    expect(calls[0].headers.get("Cookie")).toBe("energyiq_session=token");
    // The page hydrates from the same request's client.
    expect(getServerQueryClient().getQueryData(["/api/v1/auth/me"])).toEqual(USER);
  });

  it("calls /auth/me again on the next request", async () => {
    const calls = countMe(() => HttpResponse.json(USER));

    await requireSession("/");
    newRequest();
    await requireSession("/");

    expect(calls).toHaveLength(2);
  });

  it("redirects a signed out visitor to login with the path and query", async () => {
    countMe(() => problem(401, "not_authenticated"));

    const error = await requireSession("/", { tab: "week", tag: ["a", "b"] }).catch(
      (e: unknown) => e,
    );

    expect(error).toBeInstanceOf(RedirectSignal);
    expect((error as RedirectSignal).target).toBe(
      "/login?next=%2F%3Ftab%3Dweek%26tag%3Da%26tag%3Db",
    );
  });

  it("redirects a bare home visit to /login?next=%2F", async () => {
    countMe(() => problem(401, "not_authenticated"));

    await expect(requireSession("/")).rejects.toMatchObject({ target: "/login?next=%2F" });
  });

  it("reports an unreachable API as unavailable, never a login redirect", async () => {
    countMe(() => HttpResponse.error());

    await expect(requireSession("/")).resolves.toEqual({ status: "unavailable", requestId: null });
  });

  it("keeps the request id of a database_unavailable 503", async () => {
    countMe(() => problem(503, "database_unavailable"));

    await expect(requireSession("/")).resolves.toEqual({
      status: "unavailable",
      requestId: "req-123",
    });
  });

  it("lets any other problem reach error.tsx", async () => {
    countMe(() => problem(500, "internal_error"));

    await expect(requireSession("/")).rejects.toMatchObject({
      name: "ApiError",
      code: "internal_error",
    });
  });
});

describe("redirectIfSignedIn", () => {
  it("sends a signed in visitor home", async () => {
    countMe(() => HttpResponse.json(USER));

    await expect(redirectIfSignedIn()).rejects.toMatchObject({ target: "/" });
  });

  it.each([
    ["signed out", () => problem(401, "not_authenticated")],
    ["API down", () => HttpResponse.error()],
  ])("shows the page when %s", async (_name, respond) => {
    countMe(respond);

    await expect(redirectIfSignedIn()).resolves.toBeUndefined();
  });
});

describe("loginRedirectTarget", () => {
  it("encodes the whole path and query into next", () => {
    expect(loginRedirectTarget("/properties", { x: "1 2" })).toBe(
      "/login?next=%2Fproperties%3Fx%3D1%2B2",
    );
  });
});
