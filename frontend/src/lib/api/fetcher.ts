/**
 * The only module that calls `fetch` for the API (spec 0010 AC-4). Every
 * generated Orval function routes through `apiFetch`.
 *
 * - Browser: relative `/api/v1/...` URLs through the Next.js rewrite, with
 *   `credentials: "same-origin"`, so the HttpOnly session cookie travels and
 *   JavaScript never sees it.
 * - Server: the caller must pass `server` from `serverRequestInit()` (base
 *   URL, the filtered session cookie, `cache: "no-store"`). Without it this
 *   throws `ServerFetchWithoutInitError` instead of sending an anonymous
 *   request.
 */
import {
  type ApiError,
  ApiUnavailableError,
  PROBLEM_MEDIA_TYPE,
  REQUEST_ID_HEADER,
  ServerFetchWithoutInitError,
  toApiError,
} from "./errors";

export const CSRF_HEADER = "X-EnergyIQ-CSRF";
const UNSAFE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);
export const SERVER_TIMEOUT_MS = 10_000;

/** What `serverRequestInit()` supplies for a server side call. */
export type ServerInit = {
  baseUrl: string;
  cookie: string;
  cache: "no-store";
  /** Overrides `SERVER_TIMEOUT_MS`; only the consumption prefetch sets it. */
  timeoutMs?: number;
};

/**
 * What generated hooks report as their error type: Orval reads this export.
 * The problem body type parameter is ignored because the mutator never
 * throws a raw body.
 */
export type ErrorType<_Body> = ApiError | ApiUnavailableError;

/** The per call options generated functions accept (`request` in hooks). */
export type RequestOptions = RequestInit & { server?: ServerInit };

function isBrowser(): boolean {
  return typeof window !== "undefined";
}

function buildInit(url: string, options: RequestOptions): { target: string; init: RequestInit } {
  const { server, ...rest } = options;
  const method = (rest.method ?? "GET").toUpperCase();
  const headers = new Headers(rest.headers);
  if (UNSAFE_METHODS.has(method)) {
    headers.set(CSRF_HEADER, "1");
  } else {
    headers.delete(CSRF_HEADER);
  }
  if (rest.body !== undefined && rest.body !== null && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  headers.set("Accept", `application/json, ${PROBLEM_MEDIA_TYPE}`);

  if (isBrowser()) {
    return {
      target: url,
      init: { ...rest, method, headers, credentials: "same-origin" },
    };
  }
  if (server === undefined) {
    throw new ServerFetchWithoutInitError(url);
  }
  if (server.cookie) {
    headers.set("Cookie", server.cookie);
  }
  const timeout = AbortSignal.timeout(server.timeoutMs ?? SERVER_TIMEOUT_MS);
  return {
    target: `${server.baseUrl}${url}`,
    init: {
      ...rest,
      method,
      headers,
      cache: server.cache,
      signal: rest.signal ? AbortSignal.any([rest.signal, timeout]) : timeout,
    },
  };
}

async function readJson(response: Response): Promise<unknown> {
  const text = await response.text();
  return JSON.parse(text) as unknown;
}

export async function apiFetch<T>(url: string, options: RequestOptions = {}): Promise<T> {
  const { target, init } = buildInit(url, options);

  let response: Response;
  try {
    response = await fetch(target, init);
  } catch (error) {
    // An abort the caller asked for is not an outage: let React Query see it.
    if (options.signal?.aborted) {
      throw error;
    }
    const reason = error instanceof Error && error.name === "TimeoutError" ? "timeout" : "network";
    throw new ApiUnavailableError(reason);
  }

  const requestId = response.headers.get(REQUEST_ID_HEADER);
  const contentType = response.headers.get("Content-Type") ?? "";

  if (contentType.toLowerCase().startsWith(PROBLEM_MEDIA_TYPE)) {
    let body: unknown;
    try {
      body = await readJson(response);
    } catch {
      throw new ApiUnavailableError(`unreadable problem body (${response.status})`, requestId);
    }
    throw toApiError(response, body);
  }

  if (!response.ok) {
    // The bare 500 the rewrite returns when FastAPI is down, an HTML 404...
    throw new ApiUnavailableError(`unexpected ${response.status} response`, requestId);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  try {
    return (await readJson(response)) as T;
  } catch {
    throw new ApiUnavailableError(`unreadable ${response.status} body`, requestId);
  }
}

export default apiFetch;
