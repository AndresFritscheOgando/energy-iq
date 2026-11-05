/**
 * Type level proof (spec 0010 AC-3): checked by `pnpm typecheck`, since
 * `expectTypeOf` assertions are compile time only.
 */
import type { UseQueryResult } from "@tanstack/react-query";
import { describe, expectTypeOf, it } from "vitest";

import type { ErrorType, RequestOptions } from "@/lib/api/fetcher";
import { me, type useMe } from "@/lib/api/generated/auth/auth";
import type { ConsumptionSummaryResponse, Problem, UserOut } from "@/lib/api/generated/model";

describe("generated client types", () => {
  it("me resolves to UserOut and accepts RequestOptions per call", () => {
    expectTypeOf(me).returns.resolves.toEqualTypeOf<UserOut>();
    expectTypeOf(me).parameter(0).toEqualTypeOf<RequestOptions | undefined>();
  });

  it("useMe data is UserOut | undefined with the mutator's error type", () => {
    type Result = ReturnType<typeof useMe<UserOut>>;
    expectTypeOf<Result["data"]>().toEqualTypeOf<UserOut | undefined>();
    expectTypeOf<Result>().toExtend<UseQueryResult<UserOut, ErrorType<Problem>>>();
  });

  it("keeps decimals as strings", () => {
    expectTypeOf<ConsumptionSummaryResponse["measured_kwh"]>().toEqualTypeOf<string>();
  });
});
