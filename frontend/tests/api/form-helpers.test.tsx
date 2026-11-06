/** Form error mapping, idempotency keys, and meter data invalidation (spec 0011). */
import { QueryClient } from "@tanstack/react-query";
import { renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ApiError, ApiUnavailableError } from "@/lib/api/errors";
import { genericErrorMessage, problemToForm } from "@/lib/api/form-errors";
import { getGetMeterQueryKey } from "@/lib/api/generated/meters/meters";
import {
  getListReadingsQueryKey,
  getStoredConsumptionQueryKey,
} from "@/lib/api/generated/default/default";
import { invalidateMeterData, readingsListOptions } from "@/lib/api/list-queries";
import { useIdempotencyKey } from "@/lib/api/use-idempotency-key";
import { en } from "@/messages/en";

function apiError(
  status: number,
  code: string,
  errors: { loc: (string | number)[]; code: string; message: string }[] = [],
) {
  return new ApiError({
    status,
    code,
    title: "",
    detail: null,
    requestId: "req-1",
    errors,
    retryAfterSeconds: null,
  });
}

const MAP = { cumulative_kwh: "value", local_date: "date" } as const;

describe("problemToForm", () => {
  it("strips body from loc and uses en.ts copy by code", () => {
    const error = apiError(422, "validation_failed", [
      { loc: ["body", "cumulative_kwh"], code: "invalid_kwh", message: "server text" },
    ]);
    expect(problemToForm(error, MAP)).toEqual({
      fields: { value: en.fieldErrors.invalid_kwh },
      form: null,
    });
  });

  it("sends an unmapped field to the form alert", () => {
    const error = apiError(422, "validation_failed", [
      { loc: ["body", "cumulative_kwh"], code: "invalid_kwh", message: "x" },
      { loc: ["body", "other"], code: "missing", message: "x" },
    ]);
    const result = problemToForm(error, MAP);
    expect(result.fields.value).toBeDefined();
    expect(result.form).toBe(en.fieldErrorFallback);
  });

  it("ignores names that only exist on Object.prototype", () => {
    const error = apiError(422, "validation_failed", [
      { loc: ["body", "constructor"], code: "missing", message: "x" },
    ]);
    expect(problemToForm(error, MAP)).toEqual({ fields: {}, form: en.fieldErrorFallback });
  });

  it("keeps the first error per field, and falls back on an unknown code", () => {
    const error = apiError(422, "validation_failed", [
      { loc: ["body", "local_date"], code: "brand_new_code", message: "x" },
      { loc: ["body", "local_date"], code: "reading_in_future", message: "x" },
    ]);
    expect(problemToForm(error, MAP).fields.date).toBe(en.fieldErrorFallback);
  });

  it("gives anything else the generic message and never the server's text", () => {
    const conflict = apiError(409, "something");
    expect(problemToForm(conflict, MAP)).toEqual({
      fields: {},
      form: en.fallback("req-1"),
    });
    const down = new ApiUnavailableError("network");
    expect(problemToForm(down, MAP).form).toBe(en.unavailable.message);
    expect(genericErrorMessage(new Error("boom"))).toBe(en.fallback(null));
  });
});

describe("useIdempotencyKey", () => {
  it("reuses a key for the same submission and makes a new one when it changes", () => {
    const { result } = renderHook(() => useIdempotencyKey());
    const first = result.current.keyFor("a");
    expect(result.current.keyFor("a")).toBe(first);
    const second = result.current.keyFor("b");
    expect(second).not.toBe(first);
    expect(result.current.keyFor("a")).not.toBe(first);
  });

  it("makes a new key after success", () => {
    const { result } = renderHook(() => useIdempotencyKey());
    const first = result.current.keyFor("a");
    result.current.reset();
    expect(result.current.keyFor("a")).not.toBe(first);
  });
});

describe("invalidateMeterData", () => {
  const METER = "meter-1";

  it("matches every range and page of this meter, and nothing else", async () => {
    const client = new QueryClient();
    const windows = [
      { from: "2026-08-01T04:00:00Z", to: "2026-11-01T04:00:00Z" },
      { from: "2025-11-01T04:00:00Z", to: "2026-11-01T04:00:00Z" },
    ];
    const matching = [
      ...windows.map((window) => getStoredConsumptionQueryKey(METER, window)),
      readingsListOptions(METER).queryKey,
      getListReadingsQueryKey(METER, { order: "desc", to: "x", status: "valid", limit: 1 }),
    ];
    const others = [
      getStoredConsumptionQueryKey("meter-2", windows[0]),
      readingsListOptions("meter-2").queryKey,
      getGetMeterQueryKey(METER),
    ];
    for (const key of [...matching, ...others]) {
      client.setQueryData(key, { ok: true });
    }

    await invalidateMeterData(client, METER);

    for (const key of matching) {
      expect(client.getQueryState(key)?.isInvalidated, JSON.stringify(key)).toBe(true);
    }
    for (const key of others) {
      expect(client.getQueryState(key)?.isInvalidated, JSON.stringify(key)).toBe(false);
    }
  });

  it("gives infinite lists a key apart from a plain query of the same params", () => {
    const plain = getListReadingsQueryKey(METER, { order: "desc", limit: 50 });
    expect(readingsListOptions(METER).queryKey).toEqual([...plain, "infinite"]);
  });
});
