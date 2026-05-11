// A minimal data-fetching hook.
//
// We deliberately don't use React Query / SWR / Tanstack Query for a
// four-screen app. The hook has three states (loading, error, data) and
// re-runs when the deps array changes. The service worker handles caching
// at the HTTP layer, which is the right place for it.

import { useEffect, useState } from "react";

export interface FetchState<T> {
  data: T | null;
  loading: boolean;
  error: Error | null;
  refresh: () => void;
}

export function useFetch<T>(
  fetcher: () => Promise<T>,
  deps: unknown[] = []
): FetchState<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(null);
    fetcher()
      .then((d) => alive && (setData(d), setLoading(false)))
      .catch((e) => alive && (setError(e instanceof Error ? e : new Error(String(e))), setLoading(false)));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);

  return {
    data,
    loading,
    error,
    refresh: () => setTick((n) => n + 1),
  };
}
