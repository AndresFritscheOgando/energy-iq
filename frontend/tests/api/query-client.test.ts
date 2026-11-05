/**
 * Session lost mid use (spec 0010 AC-10): only a `not_authenticated` 401
 * clears the cache and navigates, and parallel 401s navigate once.
 */
import { describe, expect, it, vi } from "vitest";

import { ApiError, ApiUnavailableError } from "@/lib/api/errors";
import { createBrowserQueryClient } from "@/lib/api/query-client";

function apiError(status: number, code: string) {
  return new ApiError({
    status,
    code,
    title: "",
    detail: null,
    requestId: null,
    errors: [],
    retryAfterSeconds: null,
  });
}

function failingQuery(
  client: ReturnType<typeof createBrowserQueryClient>,
  key: string,
  error: Error,
) {
  return client
    .fetchQuery({
      queryKey: [key],
      queryFn: () => Promise.reject(error),
      retry: false,
    })
    .catch(() => undefined);
}

describe("createBrowserQueryClient", () => {
  it("clears the cache and navigates once for parallel not_authenticated 401s", async () => {
    window.history.replaceState(null, "", "/properties?view=list");
    const navigate = vi.fn();
    const client = createBrowserQueryClient(navigate);
    client.setQueryData(["/api/v1/auth/me"], { email: "owner@example.test" });

    await Promise.all(
      ["a", "b", "c"].map((key) => failingQuery(client, key, apiError(401, "not_authenticated"))),
    );

    expect(navigate).toHaveBeenCalledTimes(1);
    expect(navigate).toHaveBeenCalledWith("/login?next=%2Fproperties%3Fview%3Dlist");
    expect(client.getQueryData(["/api/v1/auth/me"])).toBeUndefined();
  });

  it("reacts to a not_authenticated mutation as well", async () => {
    const navigate = vi.fn();
    const client = createBrowserQueryClient(navigate);

    await client
      .getMutationCache()
      .build(client, { mutationFn: () => Promise.reject(apiError(401, "not_authenticated")) })
      .execute(undefined)
      .catch(() => undefined);

    expect(navigate).toHaveBeenCalledTimes(1);
  });

  it.each([
    ["login's invalid_credentials 401", apiError(401, "invalid_credentials")],
    ["a 403", apiError(403, "csrf_rejected")],
    ["an outage", new ApiUnavailableError("network")],
  ])("ignores %s", async (_name, error) => {
    const navigate = vi.fn();
    const client = createBrowserQueryClient(navigate);
    client.setQueryData(["kept"], 1);

    await failingQuery(client, "x", error);

    expect(navigate).not.toHaveBeenCalled();
    expect(client.getQueryData(["kept"])).toBe(1);
  });

  it("retries an outage once and a problem answer never", () => {
    const client = createBrowserQueryClient(vi.fn());
    const retry = client.getDefaultOptions().queries?.retry as (n: number, e: unknown) => boolean;

    expect(retry(0, new ApiUnavailableError("network"))).toBe(true);
    expect(retry(1, new ApiUnavailableError("network"))).toBe(false);
    expect(retry(0, apiError(500, "internal_error"))).toBe(false);
    expect(client.getDefaultOptions().mutations?.retry).toBe(false);
  });
});
