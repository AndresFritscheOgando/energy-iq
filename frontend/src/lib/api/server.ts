/**
 * Server side API access (spec 0010 AC-5, AC-6). The only module that reads
 * incoming cookies and, at runtime, `ENERGYIQ_API_ORIGIN`.
 *
 * - `serverRequestInit()` forwards only the session cookie and always sets
 *   `cache: "no-store"`, so no authenticated response is stored in the
 *   Next.js data cache or shared between requests.
 * - `getServerQueryClient()` is wrapped in `React.cache`: one QueryClient per
 *   server request, never shared across requests.
 * - `requireSession()` is the guard every `(app)` page awaits first.
 *   `redirect()` throws a special Next.js error, so it is never called
 *   inside a `try`.
 */
import "server-only";

import { QueryClient, type DataTag, type QueryKey } from "@tanstack/react-query";
import { cookies } from "next/headers";
import { notFound, redirect } from "next/navigation";
import { cache } from "react";

import { ApiError, ApiUnavailableError, isNotAuthenticated } from "./errors";
import type { ServerInit } from "./fetcher";
import { getMeQueryOptions } from "./generated/auth/auth";
import type { UserOut } from "./generated/model";

const DEV_API_ORIGIN = "http://127.0.0.1:8000";

/** ADR-007: the plain name in dev, the `__Host-` name when cookies are secure. */
export const SESSION_COOKIE_NAMES = ["energyiq_session", "__Host-energyiq_session"] as const;

export type SearchParams = Record<string, string | string[] | undefined>;

export type SessionState =
  { status: "signed_in"; user: UserOut } | { status: "unavailable"; requestId: string | null };

export function apiOrigin(): string {
  const value = process.env.ENERGYIQ_API_ORIGIN?.trim();
  if (value) {
    return value.replace(/\/+$/, "");
  }
  if (process.env.NODE_ENV === "production") {
    throw new Error("ENERGYIQ_API_ORIGIN is not set.");
  }
  return DEV_API_ORIGIN;
}

export async function serverRequestInit(): Promise<ServerInit> {
  const store = await cookies();
  const cookie = SESSION_COOKIE_NAMES.flatMap((name) => {
    const found = store.get(name);
    return found ? [`${name}=${found.value}`] : [];
  }).join("; ");
  return { baseUrl: apiOrigin(), cookie, cache: "no-store" };
}

export const getServerQueryClient = cache(
  () =>
    new QueryClient({
      defaultOptions: { queries: { retry: false, staleTime: Infinity } },
    }),
);

type SessionLookup = SessionState | { status: "signed_out" };

/** One `/auth/me` call per request, however many components ask. */
const lookupSession = cache(async (): Promise<SessionLookup> => {
  const client = getServerQueryClient();
  const server = await serverRequestInit();
  try {
    const user = await client.fetchQuery(getMeQueryOptions({ request: { server } }));
    return { status: "signed_in", user };
  } catch (error) {
    if (isNotAuthenticated(error)) {
      return { status: "signed_out" };
    }
    if (error instanceof ApiUnavailableError) {
      return { status: "unavailable", requestId: error.requestId };
    }
    throw error;
  }
});

/** `path` plus the page's query string, as the user requested it. */
export function pathWithQuery(path: string, searchParams: SearchParams = {}): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(searchParams)) {
    for (const item of Array.isArray(value) ? value : value === undefined ? [] : [value]) {
      query.append(key, item);
    }
  }
  const text = query.toString();
  return text ? `${path}?${text}` : path;
}

export function loginRedirectTarget(path: string, searchParams: SearchParams = {}): string {
  return `/login?next=${encodeURIComponent(pathWithQuery(path, searchParams))}`;
}

/**
 * The session guard. Signed out: redirect to `/login?next=...`. API down:
 * returns `unavailable`, and the page renders `<ApiUnavailable>`.
 */
export async function requireSession(
  path: string,
  searchParams: SearchParams = {},
): Promise<SessionState> {
  const session = await lookupSession();
  if (session.status === "signed_out") {
    redirect(loginRedirectTarget(path, searchParams));
  }
  return session;
}

/** For `/login` and `/register`: a signed in visitor goes to `/`. */
export async function redirectIfSignedIn(): Promise<void> {
  const session = await lookupSession();
  if (session.status === "signed_in") {
    redirect("/");
  }
}

export type LoadResult<T> =
  { status: "ok"; data: T } | { status: "unavailable"; requestId: string | null };

/**
 * A read a page cannot render without (spec 0011). A 404, or a 422 on a path
 * id, is the not found page, so a foreign, archived, unknown, or malformed id
 * all look the same. A lost session goes to login. An outage returns
 * `unavailable`, like `SessionState`. `redirect()` and `notFound()` throw, so
 * they run after the `try`, never inside it.
 */
export async function loadOrNotFound<T>(
  options: { queryKey: DataTag<QueryKey, T, unknown> },
  path: string,
  searchParams: SearchParams = {},
): Promise<LoadResult<T>> {
  let outcome: LoadResult<T> | "not_found" | "signed_out";
  try {
    const data = await getServerQueryClient().fetchQuery(
      options as Parameters<QueryClient["fetchQuery"]>[0],
    );
    outcome = { status: "ok", data: data as T };
  } catch (error) {
    if (isNotAuthenticated(error)) {
      outcome = "signed_out";
    } else if (error instanceof ApiError && (error.status === 404 || error.status === 422)) {
      outcome = "not_found";
    } else if (error instanceof ApiUnavailableError) {
      outcome = { status: "unavailable", requestId: error.requestId };
    } else {
      throw error;
    }
  }
  if (outcome === "signed_out") {
    redirect(loginRedirectTarget(path, searchParams));
  }
  if (outcome === "not_found") {
    notFound();
  }
  return outcome;
}
