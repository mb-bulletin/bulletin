// Small, reusable UI components. Kept in a single file for now because
// the app is small; split when any one component grows past ~50 lines.

import type { ReactNode } from "react";
import type { Announcement, DatedService } from "../api/types";
import {
  formatLanguage,
  formatLocation,
  formatServiceKind,
  formatTime,
} from "../lib/format";

// ---- App chrome -----------------------------------------------------------

export function Header({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <header
      className="bg-parish-700 text-white px-5 pb-3 pt-[calc(var(--safe-top)+0.75rem)]"
    >
      <h1 className="text-lg font-serif tracking-tight">{title}</h1>
      {subtitle && <p className="text-xs text-parish-100/80 mt-0.5">{subtitle}</p>}
    </header>
  );
}

export type Tab = "today" | "schedule" | "news" | "settings";

const TABS: Array<{ id: Tab; label: string; icon: string }> = [
  { id: "today", label: "Today", icon: "✦" },
  { id: "schedule", label: "Schedule", icon: "✓" },
  { id: "news", label: "News", icon: "✉" },
  { id: "settings", label: "Settings", icon: "⚙" },
];

export function NavBar({
  current,
  onSelect,
}: {
  current: Tab;
  onSelect: (t: Tab) => void;
}) {
  return (
    <nav
      className="fixed bottom-0 inset-x-0 bg-white border-t border-parish-200 flex justify-around pt-2"
      style={{ paddingBottom: "calc(var(--safe-bottom) + 0.5rem)" }}
    >
      {TABS.map((t) => {
        const active = t.id === current;
        return (
          <button
            key={t.id}
            onClick={() => onSelect(t.id)}
            className={`flex-1 flex flex-col items-center gap-0.5 py-1 ${
              active ? "text-parish-700" : "text-stone-500"
            }`}
            aria-label={t.label}
            aria-current={active ? "page" : undefined}
          >
            <span className="text-xl leading-none">{t.icon}</span>
            <span className="text-xs">{t.label}</span>
          </button>
        );
      })}
    </nav>
  );
}

// ---- State-feedback components -------------------------------------------

export function LoadingState({ label }: { label?: string }) {
  return (
    <div className="flex items-center justify-center py-20 text-stone-500 text-sm">
      <span className="animate-pulse">{label ?? "Loading…"}</span>
    </div>
  );
}

export function ErrorState({
  error,
  onRetry,
}: {
  error: Error;
  onRetry?: () => void;
}) {
  return (
    <div className="card mx-4 mt-6 border-amber-300 bg-amber-50">
      <p className="text-amber-900 font-medium">Couldn't reach the parish.</p>
      <p className="text-sm text-amber-800 mt-1">
        {error.message || "Network error."} The app will show cached data when available.
      </p>
      {onRetry && (
        <button
          onClick={onRetry}
          className="mt-3 text-sm font-medium text-amber-900 underline"
        >
          Try again
        </button>
      )}
    </div>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return (
    <div className="text-center text-stone-500 text-sm py-12 px-6">{children}</div>
  );
}

// ---- Domain components ---------------------------------------------------

export function ServiceRow({
  service,
  highlight = false,
}: {
  service: DatedService;
  highlight?: boolean;
}) {
  const lang = formatLanguage(service.language);
  const location = formatLocation(service.location_id);
  return (
    <div
      className={`row ${highlight ? "bg-parish-50/50 -mx-2 px-2 rounded" : ""}`}
    >
      <div className="flex-1">
        <div className="text-stone-900">
          <span className="font-medium tabular-nums">
            {formatTime(service.start_time)}
            {service.end_time && (
              <span className="text-stone-500"> – {formatTime(service.end_time)}</span>
            )}
          </span>
          <span className="ml-2">{formatServiceKind(service.kind)}</span>
          {lang && (
            <span className="text-sm text-stone-500 ml-1.5">· {lang}</span>
          )}
        </div>
        {location && (
          <div className="text-xs text-stone-500 mt-0.5">at {location}</div>
        )}
        {service.notes && (
          <div className="text-xs text-stone-600 italic mt-0.5">{service.notes}</div>
        )}
        {service.intentions.length > 0 && (
          <ul className="text-xs text-stone-600 mt-1 space-y-0.5">
            {service.intentions.map((i, n) => (
              <li key={n}>· {i}</li>
            ))}
          </ul>
        )}
      </div>
      {service.is_exception && (
        <span className="text-[10px] uppercase tracking-wider font-medium text-parish-700 bg-parish-100 px-1.5 py-0.5 rounded">
          this week
        </span>
      )}
    </div>
  );
}

export function AnnouncementCard({ a }: { a: Announcement }) {
  return (
    <article className="card">
      <h3 className="font-medium text-stone-900">{a.title}</h3>
      <p className="text-sm text-stone-700 mt-1 leading-relaxed">{a.body}</p>
      {(a.event_date || a.location || a.contact_email || a.register_url) && (
        <dl className="mt-3 text-xs space-y-1 text-stone-600">
          {a.event_date && (
            <div>
              <dt className="inline font-medium">When: </dt>
              <dd className="inline">
                {a.event_date}
                {a.event_time && ` at ${formatTime(a.event_time)}`}
              </dd>
            </div>
          )}
          {a.location && (
            <div>
              <dt className="inline font-medium">Where: </dt>
              <dd className="inline">{a.location}</dd>
            </div>
          )}
          {a.contact_email && (
            <div>
              <dt className="inline font-medium">Contact: </dt>
              <dd className="inline">
                <a className="underline" href={`mailto:${a.contact_email}`}>
                  {a.contact_email}
                </a>
              </dd>
            </div>
          )}
          {a.register_url && (
            <div className="pt-1">
              <a
                href={a.register_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-block px-3 py-1.5 bg-parish-700 text-white rounded font-medium"
              >
                Register
              </a>
            </div>
          )}
        </dl>
      )}
    </article>
  );
}
