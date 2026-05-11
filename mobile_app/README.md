# Parish Bulletin — Mobile App Shell

A small PWA that consumes the bulletin API and renders the home view a
parishioner actually wants on Sunday morning: next Mass, anything
unusual this week, the announcements that matter.

## What this is and isn't

**Is:** a functional shell that proves the API contract works end-to-end,
runs offline-friendly on a phone, and is the right starting point for
serious mobile development.

**Isn't:** a polished, store-ready app. It's intentionally minimal —
four screens, system fonts, no design system beyond a handful of
Tailwind primitives. Treat the code as a reference implementation of
the API client, not as production UI.

## Why a PWA, not React Native or native

Catholic-bulletin reading is ~95% read-only and tolerates ~1-second
loads. PWAs handle that beautifully — installable to the home screen,
offline-capable via service worker, indistinguishable from native for
content-driven apps. The trade-offs that would push toward native
(deep system integration, demanding interactions, store discovery) don't
apply here yet. And PWAs ship instantly: no certificates, no review,
shareable as a URL.

## Stack

- **Vite + React + TypeScript** — boring, fast, no surprises.
- **Tailwind CSS** — utility classes; tiny `components/ui.tsx` for the
  shared primitives. No design system library.
- **vite-plugin-pwa** — service worker + manifest. The SW caches
  `/today`, `/schedule`, and `/bulletins/current` responses with a
  stale-while-revalidate policy, so the app shows last-known data
  instantly even on flaky church-basement networks.
- **No state library, no React Query.** A four-screen read-only app
  doesn't need one. Custom 30-line `useFetch` hook does the job;
  HTTP caching does the rest.

## Running

```bash
cd mobile_app
npm install
npm run dev
```

The dev server runs at http://localhost:5173 and uses **mock data** by
default — you can verify the UI without standing up the Python API.

To run against the real API:

```bash
cp .env.example .env.local
# Edit .env.local to set VITE_API_BASE_URL, e.g. http://localhost:8000
npm run dev
```

To build for production:

```bash
npm run build
# Output: dist/
```

`dist/` is static; any CDN can serve it. The service worker and manifest
are generated at build time.

## Project layout

```
src/
  main.tsx          React entry
  App.tsx           Tab routing + parish state
  index.css         Tailwind base + small primitives
  api/
    client.ts       Typed HTTP client; mock-mode aware
    types.ts        TS types matching the API response models
    mock_data.ts    Canned data for dev/offline
  components/
    ui.tsx          Header, NavBar, ServiceRow, AnnouncementCard, states
  lib/
    format.ts       Time/date/service-kind formatters
    parish.ts       LocalStorage-backed parish selection
    useFetch.ts     Minimal data-fetching hook
  screens/
    Today.tsx       The home view — next service + this week
    Schedule.tsx    7-day calendar of services
    News.tsx        All announcements, grouped by category
    Settings.tsx    Parish selection, build info
```

## Notes on the design

**The Today screen is the product.** Everything else is secondary. The
"next service" is rendered enormous — large time, big label — because
that's what a parishioner opening the app on Sunday morning needs.

**Exceptions are visually marked.** Any service that exists because of a
`ScheduleException` (the "temporary 5pm Mass until Pentecost" pattern)
shows a small "this week" badge. This is the kind of thing parishioners
notice when something changes; the UI has to make it obvious.

**Mass intentions appear next to the service they're for**, not in a
separate list. This is one of the design choices the API enables — the
`/today` and `/schedule` endpoints already attach intentions to their
service slots, so the client doesn't have to re-correlate.

**Categories matter on the News screen.** "Safety" / safeguarding
notices aren't the same kind of thing as a film screening. Grouping by
category lets parishioners scan to what they actually want.

## What's deliberately missing

- **Parish search.** The Settings screen lists one parish. Real
  discovery (search by name/zip/map) needs an unauthenticated parish
  search endpoint we haven't built yet.
- **Auth.** No accounts. The bulletin is public; we don't need them.
- **Notifications.** PWAs support them; the use case is real ("Mass at
  9:00 in 30 min") but it's a v2 concern.
- **i18n.** All strings English; future internationalization swaps
  `lib/format.ts` and pulls strings from a catalog.
- **Tests.** A small UI shell with no client-side business logic doesn't
  benefit much from unit tests; the value is in the API tests (which
  already cover the contract this app consumes). When this app grows
  real logic, Playwright is the right next step.

## How this fits the rest of the system

```
[seeder]  -> harness.db
[harness] -> ingest weekly bulletins; parse with Claude
[api]     -> read-only HTTP served by FastAPI
[evals]   -> measure parser quality across prompt changes
[this]    -> consumer client, talks to api over HTTP
```

The app is purely a client. All state of consequence lives in the API.
That's deliberate — the day we want a native iOS app, the same API works
unchanged.
