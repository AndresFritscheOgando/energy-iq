/**
 * Mutator contract in the browser (spec 0010 AC-4). jsdom provides
 * `window`, so `apiFetch` takes its browser path with relative URLs.
 */
import { delay, http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { ApiError, ApiUnavailableError } from "@/lib/api/errors";
import { apiFetch, CSRF_HEADER } from "@/lib/api/fetcher";
import { login, logout, me } from "@/lib/api/generated/auth/auth";

import { problem, USER } from "../msw/problems";
import { server } from "../msw/server";

const ME = "*/api/v1/auth/me";
const LOGIN = "*/api/v1/auth/login";
const LOGOUT = "*/api/v1/auth/logout";

function capture() {
  const seen: Request[] = [];
  return {
    seen,
    record(request: Request) {
      seen.push(request.clone());
    },
  };
}

describe("apiFetch in the browser", () => {
  it("uses the relative path on the page origin", async () => {
    const { seen, record } = capture();
    server.use(
      http.get(ME, ({ request }) => {
        record(request);
        return HttpResponse.json(USER);
      }),
    );

    await expect(me()).resolves.toEqual(USER);

    expect(new URL(seen[0].url).origin).toBe(window.location.origin);
    expect(new URL(seen[0].url).pathname).toBe("/api/v1/auth/me");
    expect(seen[0].credentials).toBe("same-origin");
  });

  it("sends the CSRF header on unsafe methods only", async () => {
    const { seen, record } = capture();
    server.use(
      http.get(ME, ({ request }) => {
        record(request);
        return HttpResponse.json(USER);
      }),
      http.post(LOGIN, ({ request }) => {
        record(request);
        return HttpResponse.json(USER);
      }),
      http.all("*/api/v1/probe", ({ request }) => {
        record(request);
        return new HttpResponse(null, { status: 204 });
      }),
    );

    await me();
    await login({ email: "a@example.test", password: "x" });
    for (const method of ["PUT", "PATCH", "DELETE", "HEAD"]) {
      await apiFetch("/api/v1/probe", { method });
    }

    const header = (request: Request) => request.headers.get(CSRF_HEADER);
    expect(seen.map((request) => [request.method, header(request)])).toEqual([
      ["GET", null],
      ["POST", "1"],
      ["PUT", "1"],
      ["PATCH", "1"],
      ["DELETE", "1"],
      ["HEAD", null],
    ]);
  });

  it("never lets a caller send the CSRF header on a GET", async () => {
    const { seen, record } = capture();
    server.use(
      http.get(ME, ({ request }) => {
        record(request);
        return HttpResponse.json(USER);
      }),
    );

    await me({ headers: { [CSRF_HEADER]: "1" } });

    expect(seen[0].headers.get(CSRF_HEADER)).toBeNull();
  });

  it("sets JSON content type only when there is a body", async () => {
    const { seen, record } = capture();
    server.use(
      http.post(LOGIN, ({ request }) => {
        record(request);
        return HttpResponse.json(USER);
      }),
      http.post(LOGOUT, ({ request }) => {
        record(request);
        return new HttpResponse(null, { status: 204 });
      }),
    );

    await login({ email: "a@example.test", password: "x" });
    await logout();

    expect(seen[0].headers.get("Content-Type")).toBe("application/json");
    expect(seen[1].headers.get("Content-Type")).toBeNull();
  });

  it("passes a typed Idempotency-Key header through unchanged", async () => {
    const { seen, record } = capture();
    server.use(
      http.post("*/api/v1/probe", ({ request }) => {
        record(request);
        return HttpResponse.json({});
      }),
    );

    await apiFetch("/api/v1/probe", {
      method: "POST",
      body: "{}",
      headers: { "Idempotency-Key": "4f1b..." },
    });

    expect(seen[0].headers.get("Idempotency-Key")).toBe("4f1b...");
  });

  it("returns undefined for 204", async () => {
    server.use(http.post(LOGOUT, () => new HttpResponse(null, { status: 204 })));

    await expect(logout()).resolves.toBeUndefined();
  });

  it.each(["application/problem+json", "application/problem+json; charset=utf-8"])(
    "turns a %s body into ApiError",
    async (contentType) => {
      server.use(
        http.post(LOGIN, () =>
          HttpResponse.json(
            {
              title: "Too many attempts",
              status: 429,
              code: "too_many_attempts",
              request_id: "req-body",
              errors: [{ loc: ["body", "email"], code: "invalid_email", message: "m" }],
            },
            { status: 429, headers: { "Content-Type": contentType, "Retry-After": "90" } },
          ),
        ),
      );

      const error = await login({ email: "a", password: "b" }).catch((e: unknown) => e);

      expect(error).toBeInstanceOf(ApiError);
      expect(error).toMatchObject({
        status: 429,
        code: "too_many_attempts",
        title: "Too many attempts",
        requestId: "req-body",
        retryAfterSeconds: 90,
        errors: [{ loc: ["body", "email"], code: "invalid_email", message: "m" }],
      });
    },
  );

  it("falls back to the X-Request-ID header and a null Retry-After", async () => {
    server.use(
      http.get(ME, () =>
        HttpResponse.json(
          { status: 401, code: "not_authenticated", title: "Unauthorized" },
          {
            status: 401,
            headers: {
              "Content-Type": "application/problem+json",
              "X-Request-ID": "req-header",
              "Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT",
            },
          },
        ),
      ),
    );

    const error = await me().catch((e: unknown) => e);

    expect(error).toMatchObject({
      code: "not_authenticated",
      requestId: "req-header",
      retryAfterSeconds: null,
    });
  });

  it.each([
    ["a bare text 500", () => new HttpResponse("Internal Server Error", { status: 500 })],
    [
      "an HTML 404",
      () =>
        new HttpResponse("<html>not found</html>", {
          status: 404,
          headers: { "Content-Type": "text/html" },
        }),
    ],
    [
      "an unparseable 2xx",
      () =>
        new HttpResponse("{not json", {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
    ],
    ["a network error", () => HttpResponse.error()],
    ["a database_unavailable 503", () => problem(503, "database_unavailable")],
    ["a schema_out_of_date 503", () => problem(503, "schema_out_of_date")],
  ])("turns %s into ApiUnavailableError", async (_name, respond) => {
    server.use(http.get(ME, respond));

    await expect(me()).rejects.toBeInstanceOf(ApiUnavailableError);
  });

  it("keeps the request id on an unavailable 503", async () => {
    server.use(http.get(ME, () => problem(503, "database_unavailable")));

    await expect(me()).rejects.toMatchObject({ requestId: "req-123" });
  });

  it("lets a caller's abort through instead of reporting an outage", async () => {
    server.use(
      http.get(ME, async () => {
        await delay("infinite");
        return HttpResponse.json(USER);
      }),
    );
    const controller = new AbortController();

    const pending = me({ signal: controller.signal });
    controller.abort();

    await expect(pending).rejects.not.toBeInstanceOf(ApiUnavailableError);
  });
});
