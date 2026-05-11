// The Today screen — the app's home view.
//
// The hero is the next service (huge time, big label). Below that, a small
// "what else today" section, then this-week exceptions (if any) and the
// 1-3 highest-priority announcements. The intent is that a parishioner
// opens the app and gets their answer in one glance.

import { getToday } from "../api/client";
import {
  AnnouncementCard,
  EmptyState,
  ErrorState,
  Header,
  LoadingState,
  ServiceRow,
} from "../components/ui";
import { formatDate, formatLocation, formatServiceKind, formatTime } from "../lib/format";
import { useFetch } from "../lib/useFetch";

export function TodayScreen({ parishId }: { parishId: string }) {
  const { data, loading, error, refresh } = useFetch(() => getToday(parishId), [parishId]);

  if (loading) return <LoadingState />;
  if (error) return <ErrorState error={error} onRetry={refresh} />;
  if (!data) return null;

  const next = data.next_service;
  const isToday = next && next.date === data.today;

  return (
    <>
      <Header
        title={isToday ? "Today" : "Coming Up"}
        subtitle={formatDate(data.today, { weekday: true })}
      />

      <main className="px-4 pt-5 pb-24 space-y-4">
        {next ? (
          <section className="card bg-parish-700 text-white border-parish-700">
            <p className="text-xs uppercase tracking-wider text-parish-100/80">
              {isToday ? "Next" : `Next service · ${formatDate(next.date, { weekday: true })}`}
            </p>
            <p className="mt-1 text-4xl font-serif tabular-nums">
              {formatTime(next.start_time)}
            </p>
            <p className="mt-1">
              {formatServiceKind(next.kind)}
              {next.language && next.language !== "en" && (
                <span className="text-parish-100/80"> · {next.language.toUpperCase()}</span>
              )}
            </p>
            {formatLocation(next.location_id) && (
              <p className="text-sm text-parish-100/80 mt-0.5">
                at {formatLocation(next.location_id)}
              </p>
            )}
            {next.notes && (
              <p className="text-sm text-parish-100/80 italic mt-2">{next.notes}</p>
            )}
            {next.intentions.length > 0 && (
              <div className="mt-3 pt-3 border-t border-white/20">
                <p className="text-xs uppercase tracking-wider text-parish-100/80 mb-1">
                  Mass intention{next.intentions.length > 1 ? "s" : ""}
                </p>
                <ul className="text-sm space-y-0.5">
                  {next.intentions.map((i, n) => (
                    <li key={n}>{i}</li>
                  ))}
                </ul>
              </div>
            )}
          </section>
        ) : (
          <EmptyState>No upcoming services in the current bulletin.</EmptyState>
        )}

        {data.today_services_remaining.length > 1 && (
          <section className="card">
            <h2 className="font-medium text-stone-900 mb-1">Later today</h2>
            <div className="divide-y divide-parish-100">
              {data.today_services_remaining.slice(1).map((s, n) => (
                <ServiceRow key={n} service={s} />
              ))}
            </div>
          </section>
        )}

        {data.this_week_exceptions.length > 0 && (
          <section className="card">
            <h2 className="font-medium text-stone-900 mb-2">This week</h2>
            <ul className="space-y-2 text-sm text-stone-700">
              {data.this_week_exceptions.map((e, n) => (
                <li key={n}>
                  <span className="font-medium text-parish-700 capitalize">
                    {e.kind}
                  </span>
                  {": "}
                  {e.description}
                </li>
              ))}
            </ul>
          </section>
        )}

        {data.high_priority_announcements.length > 0 && (
          <section className="space-y-3">
            <h2 className="font-medium text-stone-900 px-1">Don't miss</h2>
            {data.high_priority_announcements.map((a, n) => (
              <AnnouncementCard key={n} a={a} />
            ))}
          </section>
        )}
      </main>
    </>
  );
}
