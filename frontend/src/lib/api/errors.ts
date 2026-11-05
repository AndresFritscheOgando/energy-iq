/**
 * Errors the API layer throws (spec 0010 AC-4). Every caller handles these
 * two classes; nothing else leaves `fetcher.ts`.
 */

/** One entry of a problem body's `errors` list (`ValidationErrorItem`). */
export type FieldError = {
  loc: (string | number)[];
  code: string;
  message: string;
};

export const PROBLEM_MEDIA_TYPE = "application/problem+json";
export const REQUEST_ID_HEADER = "X-Request-ID";

/** Codes on a 503 problem that mean "the server is not usable right now". */
const UNAVAILABLE_CODES = new Set(["database_unavailable", "schema_out_of_date"]);

/** An RFC 9457 problem response from FastAPI. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly title: string;
  readonly detail: string | null;
  readonly requestId: string | null;
  readonly errors: FieldError[];
  readonly retryAfterSeconds: number | null;

  constructor(init: {
    status: number;
    code: string;
    title: string;
    detail: string | null;
    requestId: string | null;
    errors: FieldError[];
    retryAfterSeconds: number | null;
  }) {
    super(`${init.status} ${init.code}`);
    this.name = "ApiError";
    this.status = init.status;
    this.code = init.code;
    this.title = init.title;
    this.detail = init.detail;
    this.requestId = init.requestId;
    this.errors = init.errors;
    this.retryAfterSeconds = init.retryAfterSeconds;
  }
}

/** The API could not be reached or did not answer in its own format. */
export class ApiUnavailableError extends Error {
  readonly requestId: string | null;

  constructor(reason: string, requestId: string | null = null) {
    super(`API unavailable: ${reason}`);
    this.name = "ApiUnavailableError";
    this.requestId = requestId;
  }
}

/** A server side API call was made without `serverRequestInit()`. */
export class ServerFetchWithoutInitError extends Error {
  constructor(url: string) {
    super(
      `API call to ${url} ran on the server without serverRequestInit(). ` +
        "Prefetch it in a Server Component with getServerQueryClient() instead.",
    );
    this.name = "ServerFetchWithoutInitError";
  }
}

export function isNotAuthenticated(error: unknown): error is ApiError {
  return error instanceof ApiError && error.status === 401 && error.code === "not_authenticated";
}

/** `Retry-After` as whole seconds; only the integer form counts. */
export function parseRetryAfter(value: string | null): number | null {
  if (value === null || !/^\s*\d+\s*$/.test(value)) {
    return null;
  }
  return Number.parseInt(value, 10);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function stringOrNull(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function fieldErrors(value: unknown): FieldError[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter(
    (item): item is FieldError =>
      isRecord(item) &&
      Array.isArray(item.loc) &&
      typeof item.code === "string" &&
      typeof item.message === "string",
  );
}

/**
 * Turn a problem body into `ApiError`, or `ApiUnavailableError` for the 503
 * codes that mean the server is not usable and for a body that is not a
 * problem at all.
 */
export function toApiError(response: Response, body: unknown): ApiError | ApiUnavailableError {
  const headerRequestId = response.headers.get(REQUEST_ID_HEADER);
  if (!isRecord(body) || typeof body.code !== "string") {
    return new ApiUnavailableError(`unreadable problem body (${response.status})`, headerRequestId);
  }
  const requestId = stringOrNull(body.request_id) ?? headerRequestId;
  if (response.status === 503 && UNAVAILABLE_CODES.has(body.code)) {
    return new ApiUnavailableError(body.code, requestId);
  }
  return new ApiError({
    status: response.status,
    code: body.code,
    title: stringOrNull(body.title) ?? "",
    detail: stringOrNull(body.detail),
    requestId,
    errors: fieldErrors(body.errors),
    retryAfterSeconds: parseRetryAfter(response.headers.get("Retry-After")),
  });
}
