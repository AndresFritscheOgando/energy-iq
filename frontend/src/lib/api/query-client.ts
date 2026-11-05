/**
 * The browser QueryClient (spec 0010 AC-10).
 *
 * A global `onError` on the query and mutation caches reacts only to a 401
 * `not_authenticated` (login's 401 is `invalid_credentials`, so it is
 * excluded by code). A once only latch makes parallel 401s cause a single
 * navigation: clear the cache, then a full page load of `/login?next=...`.
 */
import { MutationCache, QueryCache, QueryClient } from "@tanstack/react-query";

import { ApiUnavailableError, isNotAuthenticated } from "./errors";

export type Navigate = (url: string) => void;

const MAX_QUERY_RETRIES = 1;

function currentPath(): string {
  return `${window.location.pathname}${window.location.search}`;
}

export function createBrowserQueryClient(
  navigate: Navigate = (url) => window.location.assign(url),
): QueryClient {
  let sessionLost = false;

  const onError = (error: unknown) => {
    if (sessionLost || !isNotAuthenticated(error)) {
      return;
    }
    sessionLost = true;
    client.clear();
    navigate(`/login?next=${encodeURIComponent(currentPath())}`);
  };

  const client: QueryClient = new QueryClient({
    queryCache: new QueryCache({ onError }),
    mutationCache: new MutationCache({ onError }),
    defaultOptions: {
      queries: {
        // Server prefetched data is fresh on arrival; no refetch on mount.
        staleTime: 60_000,
        // Only an outage is worth one more try; a problem answer is final.
        retry: (failures, error) =>
          error instanceof ApiUnavailableError && failures < MAX_QUERY_RETRIES,
      },
      mutations: { retry: false },
    },
  });
  return client;
}
