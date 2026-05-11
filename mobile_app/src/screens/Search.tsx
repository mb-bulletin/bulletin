// Search screen. Three modes ("Near me" / "ZIP or city" / "Name"), one
// result list, optional map.
//
// Design notes:
// - The default mode is "near me" because that's the most common use case
//   (parishioner traveling, just wants nearby Mass). It auto-runs on
//   permission grant.
// - The map is a *toggle*. On a phone it eats the whole screen; many
//   users prefer the list. We persist neither — the search screen is a
//   one-shot setup tool, not the user's daily home.
// - Tapping a result both saves it as the selected parish AND navigates
//   to Today. The setup-to-value path is a single tap.

import { lazy, Suspense, useCallback, useEffect, useState } from "react";
import {
  searchParishesByLocation,
  searchParishesByPostalCode,
  searchParishesByText,
} from "../api/client";
import type { Parish } from "../api/types";
import {
  EmptyState,
  ErrorState,
  Header,
  LoadingState,
} from "../components/ui";
import { getCurrentLocation } from "../lib/geo";
import { setSelectedParish } from "../lib/parish";

// Lazy-load the map so its ~130KB only ships when the user opens it.
const ParishMap = lazy(() =>
  import("../components/ParishMap").then((m) => ({ default: m.ParishMap }))
);

type Mode = "near" | "postal" | "name";

const MODE_LABELS: Record<Mode, string> = {
  near: "Near me",
  postal: "ZIP / city",
  name: "Name",
};

interface Props {
  onParishSelected: (parish: Parish) => void;
}

export function SearchScreen({ onParishSelected }: Props) {
  const [mode, setMode] = useState<Mode>("near");
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Parish[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [showMap, setShowMap] = useState(false);
  const [searchCenter, setSearchCenter] = useState<{ lat: number; lng: number } | null>(null);

  // Wrap the three modes in one handler so the form stays unified.
  const runSearch = useCallback(async () => {
    setError(null);
    setLoading(true);
    try {
      if (mode === "near") {
        const coords = await getCurrentLocation();
        setSearchCenter({ lat: coords.latitude, lng: coords.longitude });
        const r = await searchParishesByLocation(
          coords.latitude,
          coords.longitude,
          25
        );
        setResults(r.parishes);
      } else if (mode === "postal") {
        const r = await searchParishesByPostalCode(query);
        setResults(r.parishes);
      } else {
        const r = await searchParishesByText(query);
        setResults(r.parishes);
      }
    } catch (e) {
      setError(e instanceof Error ? e : new Error(String(e)));
      setResults(null);
    } finally {
      setLoading(false);
    }
  }, [mode, query]);

  // Auto-run "near me" on mode select; for text/postal, wait for user
  // submission so we don't fire on every keystroke.
  useEffect(() => {
    if (mode === "near") {
      runSearch();
    } else {
      setResults(null);
      setError(null);
      setSearchCenter(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode]);

  const handlePick = (p: Parish) => {
    setSelectedParish(p.id, p.name);
    onParishSelected(p);
  };

  return (
    <>
      <Header title="Find a parish" />
      <main className="px-4 pt-4 pb-24 space-y-4">
        {/* Mode toggle */}
        <div role="tablist" className="flex bg-parish-100 rounded-lg p-1">
          {(Object.keys(MODE_LABELS) as Mode[]).map((m) => (
            <button
              key={m}
              role="tab"
              aria-selected={m === mode}
              onClick={() => setMode(m)}
              className={`flex-1 py-1.5 text-sm rounded ${
                m === mode
                  ? "bg-white text-parish-700 font-medium shadow-sm"
                  : "text-stone-600"
              }`}
            >
              {MODE_LABELS[m]}
            </button>
          ))}
        </div>

        {/* Input row (hidden for "near me") */}
        {mode !== "near" && (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              runSearch();
            }}
            className="flex gap-2"
          >
            <input
              type={mode === "postal" ? "search" : "text"}
              inputMode={mode === "postal" ? "numeric" : "text"}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={
                mode === "postal" ? "ZIP code or city" : "Parish name"
              }
              className="flex-1 rounded border border-parish-200 px-3 py-2"
              autoFocus
            />
            <button
              type="submit"
              disabled={!query.trim() || loading}
              className="px-4 rounded bg-parish-700 text-white font-medium disabled:opacity-50"
            >
              Search
            </button>
          </form>
        )}

        {/* Map toggle (only when we have results with coords) */}
        {results && results.some((p) => p.latitude != null) && (
          <button
            onClick={() => setShowMap((v) => !v)}
            className="text-sm font-medium text-parish-700 underline"
          >
            {showMap ? "Hide map" : "Show map"}
          </button>
        )}

        {showMap && results && (
          <Suspense fallback={<LoadingState label="Loading map…" />}>
            <ParishMap
              parishes={results.filter((p) => p.latitude != null)}
              center={searchCenter ?? undefined}
              onSelect={handlePick}
              className="h-80 rounded-lg overflow-hidden border border-parish-200"
            />
          </Suspense>
        )}

        {/* Results */}
        {loading && <LoadingState />}
        {error && <ErrorState error={error} onRetry={runSearch} />}
        {!loading && !error && results !== null && results.length === 0 && (
          <EmptyState>No parishes found. Try a different search.</EmptyState>
        )}
        {!loading && results && results.length > 0 && (
          <ul className="space-y-2">
            {results.map((p) => (
              <li key={p.id}>
                <button
                  onClick={() => handlePick(p)}
                  className="card w-full text-left active:bg-parish-50"
                >
                  <div className="font-medium text-stone-900">{p.name}</div>
                  <div className="text-sm text-stone-600 mt-0.5">
                    {[p.city, p.state].filter(Boolean).join(", ")}
                    {p.distance_km != null && (
                      <span className="ml-2 text-parish-700">
                        · {p.distance_km.toFixed(1)} km
                      </span>
                    )}
                  </div>
                  {p.diocese && (
                    <div className="text-xs text-stone-500 mt-0.5">{p.diocese}</div>
                  )}
                </button>
              </li>
            ))}
          </ul>
        )}
      </main>
    </>
  );
}
