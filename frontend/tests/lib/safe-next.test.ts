/** Open redirect table for `safeNextPath` (spec 0010 AC-11). */
import { describe, expect, it } from "vitest";

import { safeNextPath } from "@/lib/safe-next";

describe("safeNextPath", () => {
  it.each([
    "//evil.example",
    "/\\evil.example",
    "/%5Cevil.example",
    "https://evil.example",
    "/%2F%2Fevil.example",
    "/%252F%252Fevil.example",
    "javascript:alert(1)",
    "",
    "/login",
    "/login/",
    "/login?x=1",
    "/register#a",
    "/api/v1/auth/logout",
    "/api",
    "/API/v1/auth/logout",
    "/./api/v1/auth/logout",
    "/%2e/login",
    "/properties\u0000",
    "/properties%0d%0aSet-Cookie:x",
    "relative/path",
    "/%E0%A4%A",
  ])("rejects %j", (value) => {
    expect(safeNextPath(value)).toBe("/");
  });

  it.each(["/properties?x=1", "/", "/properties/42#readings", "/apiary", "/logins"])(
    "keeps %j",
    (value) => {
      expect(safeNextPath(value)).toBe(value);
    },
  );

  it("treats a missing value as home", () => {
    expect(safeNextPath(null)).toBe("/");
    expect(safeNextPath(undefined)).toBe("/");
  });
});
