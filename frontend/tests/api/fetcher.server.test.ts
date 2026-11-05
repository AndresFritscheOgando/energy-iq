// @vitest-environment node
/**
 * Mutator contract on the server (spec 0010 AC-4): no `window`, so a call
 * needs `serverRequestInit()` and carries a timeout.
 */
import { delay, http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiUnavailableError, ServerFetchWithoutInitError } from "@/lib/api/errors";
import type { ServerInit } from "@/lib/api/fetcher";
import { me } from "@/lib/api/generated/auth/auth";

import { USER } from "../msw/problems";
import { server } from "../msw/server";

const INIT: ServerInit = {
  baseUrl: "http://api.test:8000",
  cookie: "energyiq_session=abc",
  cache: "no-store",
};

afterEach(() => {
  vi.useRealTimers();
});

describe("apiFetch on the server", () => {
  it("refuses to send an anonymous request without serverRequestInit", async () => {
    await expect(me()).rejects.toBeInstanceOf(ServerFetchWithoutInitError);
  });

  it("uses the base URL, the forwarded cookie, and no-store", async () => {
    const seen: Request[] = [];
    server.use(
      http.get("http://api.test:8000/api/v1/auth/me", ({ request }) => {
        seen.push(request);
        return HttpResponse.json(USER);
      }),
    );

    const fetchSpy = vi.spyOn(globalThis, "fetch");

    await expect(me({ server: INIT })).resolves.toEqual(USER);

    expect(seen[0].headers.get("Cookie")).toBe("energyiq_session=abc");
    const init = fetchSpy.mock.calls[0][1];
    expect(init?.cache).toBe("no-store");
    expect(init?.signal).toBeInstanceOf(AbortSignal);
  });

  it("reports a timeout as ApiUnavailableError", async () => {
    vi.spyOn(AbortSignal, "timeout").mockImplementation(() =>
      AbortSignal.abort(new DOMException("The operation timed out.", "TimeoutError")),
    );
    server.use(
      http.get("http://api.test:8000/api/v1/auth/me", async () => {
        await delay("infinite");
        return HttpResponse.json(USER);
      }),
    );

    const error = await me({ server: INIT }).catch((e: unknown) => e);

    expect(AbortSignal.timeout).toHaveBeenCalledWith(10_000);
    expect(error).toBeInstanceOf(ApiUnavailableError);
    expect((error as Error).message).toContain("timeout");
  });

  it("reports a refused connection as ApiUnavailableError with no request id", async () => {
    server.use(http.get("http://api.test:8000/api/v1/auth/me", () => HttpResponse.error()));

    await expect(me({ server: INIT })).rejects.toMatchObject({
      name: "ApiUnavailableError",
      requestId: null,
    });
  });
});
