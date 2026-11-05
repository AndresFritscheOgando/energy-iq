/** Error to copy mapping for the auth forms (spec 0010 AC-7, AC-8, AC-12). */
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  authProblem,
  genericErrorMessage,
  minutesToWait,
  suggestedDevOrigin,
} from "@/components/auth/auth-errors";
import { ApiError, ApiUnavailableError, type FieldError } from "@/lib/api/errors";
import { en } from "@/messages/en";

function apiError(
  status: number,
  code: string,
  extra: { errors?: FieldError[]; retryAfterSeconds?: number | null; requestId?: string } = {},
) {
  return new ApiError({
    status,
    code,
    title: "",
    detail: "server detail",
    requestId: extra.requestId ?? "req-1",
    errors: extra.errors ?? [],
    retryAfterSeconds: extra.retryAfterSeconds ?? null,
  });
}

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("minutesToWait", () => {
  it.each([
    [1, 1],
    [60, 1],
    [61, 2],
    [600, 10],
    [0, 1],
    [null, null],
  ])("%s seconds is %s minutes", (seconds, minutes) => {
    expect(minutesToWait(seconds)).toBe(minutes);
  });
});

describe("authProblem", () => {
  it("shows invalid_credentials as one form message", () => {
    expect(authProblem(apiError(401, "invalid_credentials"), "login")).toEqual({
      fields: {},
      form: "Email or password is incorrect.",
    });
  });

  it.each([
    [600, "Too many attempts. Try again in 10 minutes."],
    [45, "Too many attempts. Try again in 1 minute."],
    [null, "Too many attempts. Try again later."],
  ])("shows a 429 with Retry-After %s", (retryAfterSeconds, message) => {
    const error = apiError(429, "too_many_attempts", { retryAfterSeconds });

    expect(authProblem(error, "login").form).toBe(message);
  });

  it("maps 422 errors to fields by loc and code, never the server message", () => {
    const error = apiError(422, "validation_error", {
      errors: [
        { loc: ["body", "password"], code: "password_length", message: "SERVER TEXT" },
        { loc: ["body", "email"], code: "brand_new_code", message: "SERVER TEXT" },
      ],
    });

    const found = authProblem(error, "register");

    expect(found).toEqual({
      fields: {
        password: { message: en.fieldErrors.password_length },
        email: { message: "This value is not valid." },
      },
      form: null,
    });
    expect(JSON.stringify(found)).not.toContain("SERVER TEXT");
  });

  it("sends 422 errors it cannot map to the form alert", () => {
    const error = apiError(422, "validation_error", {
      errors: [{ loc: ["body"], code: "invalid_type", message: "x" }],
    });

    expect(authProblem(error, "login")).toEqual({ fields: {}, form: "This value is not valid." });
  });

  it("puts email_taken on the email field with the sign in link flag", () => {
    expect(authProblem(apiError(409, "email_taken"), "register")).toEqual({
      fields: {
        email: { message: "An account with this email already exists.", emailTaken: true },
      },
      form: null,
    });
  });

  it("uses the shared fallback with the reference for other problems", () => {
    expect(authProblem(apiError(500, "internal_error"), "login").form).toBe(
      "Something went wrong. Reference: req-1.",
    );
  });
});

describe("genericErrorMessage", () => {
  it("points csrf_rejected in development at the trusted-origin setting", () => {
    vi.stubEnv("NODE_ENV", "development");

    // jsdom serves the page from http://localhost:3000, already a localhost origin.
    const message = genericErrorMessage(apiError(403, "csrf_rejected"));
    expect(message).toBe(en.csrfRejected.development(null));
    expect(message).toContain("ENERGYIQ_TRUSTED_ORIGINS");
    expect(message).not.toContain("localhost:3000");
  });

  it("names the localhost form of the page's own port for a loopback IP", () => {
    expect(en.csrfRejected.development(suggestedDevOrigin("http://127.0.0.1:3100"))).toContain(
      "Open http://localhost:3100,",
    );
  });

  it("uses a generic security message for csrf_rejected in production", () => {
    vi.stubEnv("NODE_ENV", "production");

    expect(genericErrorMessage(apiError(403, "csrf_rejected"))).toBe(en.csrfRejected.production);
  });

  it("shows the unavailable message for an outage", () => {
    expect(genericErrorMessage(new ApiUnavailableError("network"))).toBe(
      "EnergyIQ can't reach its server right now.",
    );
  });
});

describe("suggestedDevOrigin", () => {
  it.each([
    ["http://127.0.0.1:3000", "http://localhost:3000"],
    ["http://127.0.0.1:3100", "http://localhost:3100"],
    ["http://[::1]:4000", "http://localhost:4000"],
    ["http://127.0.0.1", "http://localhost"],
  ])("rewrites loopback %s to %s", (origin, expected) => {
    expect(suggestedDevOrigin(origin)).toBe(expected);
  });

  it.each([["http://localhost:3100"], ["https://app.example.com"], ["not a url"], [null]])(
    "suggests nothing for %s",
    (origin) => {
      expect(suggestedDevOrigin(origin)).toBeNull();
    },
  );
});
