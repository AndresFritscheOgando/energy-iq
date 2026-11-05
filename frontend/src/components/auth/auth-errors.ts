/**
 * Map an auth API error to what the form shows (spec 0010 AC-7, AC-8, AC-12).
 * Copy always comes from `en.ts`; the server's `message` is never shown.
 */
import { ApiError, ApiUnavailableError } from "@/lib/api/errors";
import { en } from "@/messages/en";

export type CredentialField = "email" | "password";

export type FieldProblem = { message: string; emailTaken?: boolean };

export type FormProblem = {
  fields: Partial<Record<CredentialField, FieldProblem>>;
  form: string | null;
};

const CREDENTIAL_FIELDS: readonly string[] = ["email", "password"];

export function minutesToWait(retryAfterSeconds: number | null): number | null {
  if (retryAfterSeconds === null || !Number.isFinite(retryAfterSeconds) || retryAfterSeconds < 0) {
    return null;
  }
  return Math.max(1, Math.ceil(retryAfterSeconds / 60));
}

const LOOPBACK_HOSTS = new Set(["127.0.0.1", "[::1]"]);

/**
 * The usual dev CSRF miss is opening the app on a loopback IP instead of
 * `localhost` (a different origin). Suggest the `localhost` form on the same
 * port; return null when the page already uses `localhost` or a real host,
 * because then only the API's trusted-origin list can be wrong.
 */
export function suggestedDevOrigin(pageOrigin: string | null): string | null {
  if (pageOrigin === null) {
    return null;
  }
  let url: URL;
  try {
    url = new URL(pageOrigin);
  } catch {
    return null;
  }
  if (!LOOPBACK_HOSTS.has(url.hostname)) {
    return null;
  }
  url.hostname = "localhost";
  return url.origin;
}

function currentPageOrigin(): string | null {
  return typeof window === "undefined" ? null : window.location.origin;
}

/** The shared message for errors no form handles specially (AC-12). */
export function genericErrorMessage(error: unknown): string {
  if (error instanceof ApiUnavailableError) {
    return en.unavailable.message;
  }
  if (error instanceof ApiError) {
    if (error.status === 403 && error.code === "csrf_rejected") {
      return process.env.NODE_ENV === "production"
        ? en.csrfRejected.production
        : en.csrfRejected.development(suggestedDevOrigin(currentPageOrigin()));
    }
    return en.fallback(error.requestId);
  }
  return en.fallback(null);
}

function fieldName(loc: (string | number)[]): CredentialField | null {
  const path = loc[0] === "body" ? loc.slice(1) : loc;
  const name = path[0];
  return typeof name === "string" && CREDENTIAL_FIELDS.includes(name)
    ? (name as CredentialField)
    : null;
}

function validationProblem(error: ApiError): FormProblem {
  const fields: FormProblem["fields"] = {};
  let unmapped = false;
  for (const item of error.errors) {
    const name = fieldName(item.loc);
    if (name === null) {
      unmapped = true;
      continue;
    }
    fields[name] ??= { message: en.fieldErrors[item.code] ?? en.fieldErrorFallback };
  }
  const form = unmapped || Object.keys(fields).length === 0 ? en.fieldErrorFallback : null;
  return { fields, form };
}

export function authProblem(error: unknown, operation: "login" | "register"): FormProblem {
  if (error instanceof ApiError) {
    if (error.status === 422) {
      return validationProblem(error);
    }
    if (error.status === 429 && error.code === "too_many_attempts") {
      return { fields: {}, form: en.tooManyAttempts(minutesToWait(error.retryAfterSeconds)) };
    }
    if (operation === "login" && error.status === 401 && error.code === "invalid_credentials") {
      return { fields: {}, form: en.login.invalidCredentials };
    }
    if (operation === "register" && error.status === 409 && error.code === "email_taken") {
      return {
        fields: { email: { message: en.register.emailTaken, emailTaken: true } },
        form: null,
      };
    }
  }
  return { fields: {}, form: genericErrorMessage(error) };
}
