/**
 * Paged list queries, shared by server prefetch and browser hooks (spec 0011).
 * Keys are the generated key without the cursor, plus `"infinite"`, so they
 * never collide with a plain query and still match by prefix.
 */
import { infiniteQueryOptions, type QueryClient } from "@tanstack/react-query";

import type { RequestOptions } from "./fetcher";
import {
  getListReadingsQueryKey,
  getStoredConsumptionQueryKey,
  listReadings,
} from "./generated/default/default";
import { getListMetersQueryKey, listMeters } from "./generated/meters/meters";
import { getListPropertiesQueryKey, listProperties } from "./generated/properties/properties";

const PAGE_SIZE = 50;

const NO_CURSOR = undefined as string | undefined;

function nextCursor(page: { next_cursor: string | null }): string | undefined {
  return page.next_cursor ?? undefined;
}

export function propertiesListOptions(request?: RequestOptions) {
  const params = { limit: PAGE_SIZE };
  return infiniteQueryOptions({
    queryKey: [...getListPropertiesQueryKey(params), "infinite"],
    queryFn: ({ pageParam, signal }) =>
      listProperties({ ...params, cursor: pageParam }, { ...request, signal }),
    initialPageParam: NO_CURSOR,
    getNextPageParam: nextCursor,
  });
}

export function metersListOptions(propertyId: string, request?: RequestOptions) {
  const params = { include_inactive: true, limit: PAGE_SIZE };
  return infiniteQueryOptions({
    queryKey: [...getListMetersQueryKey(propertyId, params), "infinite"],
    queryFn: ({ pageParam, signal }) =>
      listMeters(propertyId, { ...params, cursor: pageParam }, { ...request, signal }),
    initialPageParam: NO_CURSOR,
    getNextPageParam: nextCursor,
  });
}

export function readingsListOptions(meterId: string, request?: RequestOptions) {
  const params = { order: "desc", limit: PAGE_SIZE } as const;
  return infiniteQueryOptions({
    queryKey: [...getListReadingsQueryKey(meterId, params), "infinite"],
    queryFn: ({ pageParam, signal }) =>
      listReadings(meterId, { ...params, cursor: pageParam }, { ...request, signal }),
    initialPageParam: NO_CURSOR,
    getNextPageParam: nextCursor,
  });
}

/** Every readings and consumption query for this meter: all ranges, all pages. */
export function invalidateMeterData(client: QueryClient, meterId: string): Promise<unknown> {
  return Promise.all([
    client.invalidateQueries({ queryKey: getListReadingsQueryKey(meterId) }),
    client.invalidateQueries({ queryKey: getStoredConsumptionQueryKey(meterId) }),
  ]);
}
