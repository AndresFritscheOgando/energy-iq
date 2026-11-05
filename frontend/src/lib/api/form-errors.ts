/**
 * Map an API error to what a form shows (spec 0011). Copy always comes from
 * `en.ts`; the server's `message` is never shown.
 */
import { en } from "@/messages/en";

import { ApiError, ApiUnavailableError } from "./errors";

export type FormErrors<F extends string> = {
  fields: Partial<Record<F, string>>;
  form: string | null;
};

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

/** The shared message for errors no form handles specially. */
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

/**
 * A 422's field errors, through `fieldMap` (API field name to form field). The
 * first error per field wins. Unmapped errors go to the form alert, as does
 * anything that is not a 422.
 */
export function problemToForm<F extends string>(
  error: unknown,
  fieldMap: Readonly<Record<string, F>>,
): FormErrors<F> {
  if (!(error instanceof ApiError) || error.status !== 422) {
    return { fields: {}, form: genericErrorMessage(error) };
  }
  const fields: Partial<Record<F, string>> = {};
  let unmapped = false;
  for (const item of error.errors) {
    const path = item.loc[0] === "body" ? item.loc.slice(1) : item.loc;
    const apiName = path[0];
    const name =
      typeof apiName === "string" && Object.hasOwn(fieldMap, apiName) ? fieldMap[apiName] : null;
    if (name === null) {
      unmapped = true;
      continue;
    }
    fields[name] ??= en.fieldErrors[item.code] ?? en.fieldErrorFallback;
  }
  const form = unmapped || Object.keys(fields).length === 0 ? en.fieldErrorFallback : null;
  return { fields, form };
}
