// News screen — every announcement in the current bulletin.
//
// Sorted by priority ascending (so the most important shows first). Each
// announcement gets a category chip; categories like 'safety' are
// styled distinctively because they communicate something different
// from an event invitation.

import { getCurrentBulletin } from "../api/client";
import {
  AnnouncementCard,
  EmptyState,
  ErrorState,
  Header,
  LoadingState,
} from "../components/ui";
import { useFetch } from "../lib/useFetch";
import type { AnnouncementCategory } from "../api/types";

const CATEGORY_LABELS: Record<AnnouncementCategory, string> = {
  event: "Event",
  schedule_change: "Schedule",
  sacramental: "Sacramental",
  ministry: "Ministry",
  stewardship: "Stewardship",
  safety: "Safeguarding",
  operational: "Parish life",
  other: "Other",
};

export function NewsScreen({ parishId }: { parishId: string }) {
  const { data, loading, error, refresh } = useFetch(
    () => getCurrentBulletin(parishId),
    [parishId]
  );

  if (loading) return <LoadingState />;
  if (error) return <ErrorState error={error} onRetry={refresh} />;
  if (!data) return null;

  const sorted = [...data.announcements].sort((a, b) => a.priority - b.priority);

  // Group by category for a tidier scroll view.
  const groups = new Map<AnnouncementCategory, typeof sorted>();
  for (const a of sorted) {
    const arr = groups.get(a.category) ?? [];
    arr.push(a);
    groups.set(a.category, arr);
  }

  return (
    <>
      <Header title="News" subtitle={data.parish.name} />
      <main className="px-4 pt-5 pb-24 space-y-6">
        {sorted.length === 0 && <EmptyState>No announcements this week.</EmptyState>}
        {Array.from(groups.entries()).map(([cat, items]) => (
          <section key={cat} className="space-y-3">
            <h2 className="text-xs uppercase tracking-wider text-stone-500 font-medium px-1">
              {CATEGORY_LABELS[cat]}
            </h2>
            {items.map((a, n) => (
              <AnnouncementCard key={n} a={a} />
            ))}
          </section>
        ))}
      </main>
    </>
  );
}
