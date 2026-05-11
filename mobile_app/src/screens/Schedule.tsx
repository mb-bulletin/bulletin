// Schedule screen — services for the next 7 days, grouped by date.
//
// Each day is a card. Within each day, services are listed chronologically
// with exceptions visually marked. Days with no services are omitted so
// the screen doesn't pad itself with empty cells.

import { getSchedule } from "../api/client";
import {
  EmptyState,
  ErrorState,
  Header,
  LoadingState,
  ServiceRow,
} from "../components/ui";
import { formatDate } from "../lib/format";
import { useFetch } from "../lib/useFetch";
import type { DatedService } from "../api/types";

export function ScheduleScreen({ parishId }: { parishId: string }) {
  const { data, loading, error, refresh } = useFetch(
    () => getSchedule(parishId, 7),
    [parishId]
  );

  if (loading) return <LoadingState />;
  if (error) return <ErrorState error={error} onRetry={refresh} />;
  if (!data) return null;

  // Group by date, preserving service order within each day.
  const groups = new Map<string, DatedService[]>();
  for (const s of data.services) {
    const list = groups.get(s.date) ?? [];
    list.push(s);
    groups.set(s.date, list);
  }
  const dates = Array.from(groups.keys()).sort();

  return (
    <>
      <Header title="Schedule" subtitle={`Next ${data.days} days`} />
      <main className="px-4 pt-5 pb-24 space-y-3">
        {dates.length === 0 && (
          <EmptyState>No services on the calendar in this window.</EmptyState>
        )}
        {dates.map((date) => (
          <section key={date} className="card">
            <h2 className="font-medium text-stone-900">
              {formatDate(date, { weekday: true })}
            </h2>
            <div className="divide-y divide-parish-100 mt-1">
              {groups.get(date)!.map((s, n) => (
                <ServiceRow key={n} service={s} />
              ))}
            </div>
          </section>
        ))}
      </main>
    </>
  );
}
