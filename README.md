# Catholic Bulletin Parser

Turns weekly Catholic parish bulletins (PDFs) into structured JSON that a
mobile or web app can render cleanly. The output schema is shaped around
what parishioners actually want to see — *this week's* Mass times (with
exceptions surfaced explicitly), confessions, announcements, and Mass
intentions — not around how bulletins happen to be laid out.

## Why an LLM, not regex

Every parish writes their bulletin differently:

- One uses "Saturday Vigil 5:00pm English" in a tidy table.
- Another writes "Sat 4:30p +Robert Kowalski (Kowalski family)".
- A third buries "(temporary until Pentecost, May 24)" in a
  parenthetical that *negates the recurrence* of the preceding line.

Regex shatters on this. Claude reads the bulletin the way a human would:
it knows that a "+" prefix means the intention is for a deceased person,
that "until Pentecost" is a date-bounded exception, and that "WhatsApp
Announcements" is a section header, not a thing to announce.

## Architecture

```
PDF ──► extract.py ──► raw text ──► parser.py (Claude tool-use) ──► Bulletin ──► JSON
                                              ▲
                                              │
                                       schema.py (Pydantic)
```

- **`schema.py`** — Pydantic models defining the output contract.
  `Bulletin` is the top-level type. Designed for consumption: e.g.,
  `recurring_schedule` and `schedule_exceptions` are separate fields so
  the app can compute "today's actual Mass times" without reparsing
  prose.

- **`extract.py`** — pulls text out of a bulletin PDF using pdfplumber,
  falling back to `pdftotext -layout`. Multi-column layouts are common
  in bulletins; both tools handle them adequately.

- **`parser.py`** — calls Claude with a system prompt that teaches the
  conventions of Catholic bulletins (intention phrasing, exception
  phrasing, etc.) and a tool whose input schema *is* the Pydantic
  schema. The model is constrained to produce valid JSON.

- **CLI** — `python -m bulletin_parser bulletin.pdf -o bulletin.json`.

## Running

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
python -m bulletin_parser fixtures/stpatricks_20260510.txt -o parsed.json
```

The CLI accepts `.pdf` or `.txt` input. For the test fixtures (already
text-extracted), the `.txt` path skips PDF extraction.

## Schema highlights

- **`recurring_schedule`**: regular weekly slots. Each has a weekday,
  time, kind (Mass, confession, adoration, etc.), language, and location.
- **`schedule_exceptions`**: one-off changes — added, cancelled, moved,
  modified — keyed to specific dates. The "temporary 5pm Mass until
  Pentecost" from the St Patrick's bulletin becomes an `added` exception
  with an `end_date`, not a recurring slot.
- **`mass_intentions`**: each intention gets its own record. Multiple
  intentions at the same Mass time are separate records. Deceased
  intentions are flagged.
- **`announcements`**: each blurb categorized (event, sacramental,
  ministry, stewardship, safety, operational, …) and *prioritized*
  (1=must-see, 10=evergreen filler) so the app can sort.
- **`locations`**: a bulletin can cover multiple worship sites; every
  schedule/intention/collection record references a `location_id`.

See `example_output.json` for the full shape produced from the
St Patrick's Old Cathedral fixture.

## Tests

```bash
PYTHONPATH=. python tests/test_schema.py
```

Eight tests covering the schema, JSON round-tripping, and tricky cases
(temporary Mass as exception, multilingual schedules, deceased-flag
inference, multi-intention slots). These run without an API key.

## Test fixtures

- `fixtures/stpatricks_20260510.txt` — Basilica of St. Patrick's Old
  Cathedral, NYC. ecatholic.com vendor layout, two worship sites,
  four spoken Mass languages, a "temporary until Pentecost" exception.
- `fixtures/stmargaretmary_20260517.txt` — Synthetic suburban parish in
  a deliberately different format: ASCII-art section dividers, "+"
  prefix for deceased intentions, weekly schedule with day-grouping
  (Mon/Wed/Fri), wedding banns, anniversary notations. Verifies the
  parser doesn't overfit to the ecatholic layout.

## Production notes

- **Ingestion**: see the harness, below.
- **Caching**: store `raw_text_sha256` and skip reparsing identical
  bulletins. ~70% of weekly content is the same evergreen
  announcements; reparsing every week is wasteful.
- **Cost**: each bulletin is ~2-4K tokens in, ~3-5K tokens out. With
  Claude Haiku for parsing (the task isn't reasoning-heavy once the
  prompt is good), the per-bulletin cost is well under a cent.
- **Quality monitoring**: keep the hand-built reference fixtures
  in `tests/` and run the live parser against them on every prompt
  change. Track which fields drift.
- **Languages**: the schema supports many languages on `Mass.language`,
  but the system prompt assumes English bulletin text. Spanish or
  bilingual bulletins (common in many dioceses) will need a localized
  prompt or a translation step upstream.

---

# Ingestion Harness

The harness (`bulletin_parser.harness`) is the scheduled job that
discovers, fetches, dedupes, parses, and stores bulletins for a roster
of parishes.

## Quick start

```bash
# Initialize and load the example roster
python -m bulletin_parser.harness --db harness.db --pdfs ./pdfs \
    init --roster example_roster.json

# Inspect the roster
python -m bulletin_parser.harness --db harness.db --pdfs ./pdfs list-parishes

# Run one ingestion pass (this is what cron calls)
export ANTHROPIC_API_KEY=sk-ant-...
python -m bulletin_parser.harness --db harness.db --pdfs ./pdfs run

# Show health and recent attempts
python -m bulletin_parser.harness --db harness.db --pdfs ./pdfs status
```

Cron entry for Saturday evening (after most parishes have posted the
upcoming Sunday's bulletin):

```cron
0 18 * * SAT  cd /opt/bulletin-parser && \
              ANTHROPIC_API_KEY=... \
              python -m bulletin_parser.harness \
                --db harness.db --pdfs ./pdfs run
```

## How it works

```
        ┌──────────┐  per-parish:                            ┌────────────────┐
roster→ │Discovery │ ── URL ──► Fetcher ── PDF ──► dedup ──► │Storage         │
        └──────────┘                                  │      │ • bulletins    │
              │                                       └──┐   │ • parsed_blt.  │
              ▼ logs ───────────────────────────────────►│   │ • fetch log    │
           per-step audit                                │   └────────────────┘
                                                        ▼
                                                     Parser (Claude tool-use)
```

- **Discovery** resolves a parish to a current bulletin URL. Three
  strategies: `ecatholic` (probe predictable CDN URLs with HEAD), 
  `generic_html` (scrape the parish's `/bulletins` page for PDF links),
  `manual_url` (a fixed URL that always serves the latest).

- **Fetcher** is the polite HTTP layer: one request at a time per host,
  a configurable inter-request delay (default 1s), respect for
  `robots.txt`, identifying User-Agent, content-type validation (rejects
  HTML error pages disguised as 200 OK), and a 20MB body cap.

- **Storage** is SQLite. Four tables: `parishes` (roster),
  `fetch_attempts` (one row per HTTP attempt, the audit log),
  `bulletins` (one row per distinct fetched PDF, deduped by content
  hash), `parsed_bulletins` (one row per parse — multiple parses
  possible across parser versions, useful when iterating on the prompt).

- **Orchestrator** ties it together. Parallelism is across hosts
  (default 4 workers); within a host the Fetcher serializes. Every
  outcome — `new`, `unchanged`, `http_error`, `not_found`,
  `discovery_failed`, `parse_error` — is logged. A parse failure does
  NOT discard the PDF; it's still stored so it can be reparsed after
  fixing the prompt.

## Re-parsing after prompt changes

When you improve the prompt, re-parse stored PDFs without re-fetching:

```bash
python -m bulletin_parser.harness --db harness.db --pdfs ./pdfs \
    reparse --limit 200 --model claude-opus-4-5
```

The new parse is stored alongside the old one in `parsed_bulletins`
(keyed by `(bulletin_id, parser_version, model)`), so you can diff and
track quality regressions.

## Roster format

A roster is a JSON array (or CSV) of parish records. Required fields:
`id`, `name`, `host_kind`. Then one of: `ecatholic_id`,
`bulletins_url`, or `manual_url` depending on `host_kind`. See
`example_roster.json`.

## Adding parishes by hand

```bash
python -m bulletin_parser.harness --db harness.db --pdfs ./pdfs \
    add-parish --id ny-st-jane --name "St. Jane Frances de Chantal" \
    --host-kind ecatholic --ecatholic-id 12345 \
    --diocese "Archdiocese of New York" --city Bronx --state NY
```

## Operating in production

Two things to watch from day one:

1. **`status` over time.** A parish that suddenly starts returning
   `discovery_failed` probably changed CMS vendors; a parish stuck on
   `unchanged` for >2 weeks probably stopped publishing. Both are
   worth a periodic alert.
2. **Parse quality drift.** Save a few hand-curated reference parses
   in `tests/` and rerun them whenever you change the system prompt
   or the model. Field-level diffs are the right signal — total
   character count tells you almost nothing.

---

# HTTP API

The API (`bulletin_parser.api`) is a read-only FastAPI service over the
SQLite DB the harness writes. It's the contract the mobile and web apps
consume.

## Quick start

```bash
pip install -r requirements.txt
python -m bulletin_parser.api --db ./harness.db --pdfs ./pdfs \
    --host 0.0.0.0 --port 8000
```

The OpenAPI spec is at `/openapi.json` and an interactive Swagger UI is
at `/docs` (FastAPI gives both for free).

## Endpoints

```
GET  /v1/parishes                              — listing
GET  /v1/parishes/{id}                         — parish info
GET  /v1/parishes/{id}/today                   — home-screen view
GET  /v1/parishes/{id}/bulletins/current       — full latest bulletin
GET  /v1/parishes/{id}/bulletins/{YYYY-MM-DD}  — specific Sunday's bulletin
GET  /v1/parishes/{id}/schedule?days=7         — next N days of services
GET  /health                                   — for load balancers
```

HEAD is supported on all GET routes for CDN cache validation.

## The `today` endpoint is the important one

This is what the mobile home screen renders. It's the only endpoint
that does real computation: it merges the recurring weekly schedule
with this week's exceptions, filters out services that already
happened today (in the parish timezone), and surfaces high-priority
announcements (priority ≤ 3). The client renders this directly.

```json
{
  "parish_id": "ny-old-st-patricks",
  "as_of": "2026-05-11T13:02:10-04:00",
  "today": "2026-05-11",
  "next_service": {
    "date": "2026-05-12", "start_time": "12:10", "kind": "mass",
    "language": "en", "location_id": "main",
    "intentions": ["✝ Maria Filomena Nuñez (req. by Agustina Rodriguez)",
                   "Fausto Ortiz (req. by family)"]
  },
  "today_services_remaining": [],
  "this_week_exceptions": [{"kind": "added", "date": "2026-05-10", ...}],
  "high_priority_announcements": [...],
  "todays_intentions": [...]
}
```

See `example_responses/today.json` and `example_responses/schedule.json`
for full samples.

## Caching

The API leans hard on HTTP caching. The parser already stores
`content_sha256` for every bulletin PDF; that hash drives the ETag.
A typical week looks like:

- Saturday: harness fetches and parses Sunday's bulletin. ETag changes.
- Sunday–Friday: clients hit the CDN. ETag is stable, requests return
  `304 Not Modified`. Origin sees ~zero traffic.

Headers:

| Endpoint | Cache-Control |
|----------|---------------|
| `/bulletins/current`, `/bulletins/{date}` | `public, max-age=3600, stale-while-revalidate=86400` |
| `/today`, `/schedule` | `public, max-age=300, stale-while-revalidate=3600` |

The shorter TTL on `today` is because the response depends on the
current time — at midnight in the parish timezone, "tomorrow"
becomes "today" and the answer changes.

## Auth

None in v1. Bulletins are already public information published by
the parish. The day you add a parish-facing write API (corrections,
manual uploads), that becomes a separate authenticated surface —
don't bolt auth onto the read API.

## Architecture

Three layers, separated deliberately:

- **`api/repository.py`** — pure data access over Storage. Returns
  domain objects (`Bulletin`, `ParishSummary`, `BulletinRecord`).
  Swap to Postgres later by changing this file only.
- **`api/views.py`** — the today/schedule computation. Takes a
  `Bulletin` + timezone, returns `TodayView` / `list[DatedService]`.
  All the exception-merge logic lives here, with 15 view tests
  covering added/cancelled/moved exceptions, weekday filtering,
  timezone-aware "next service," and mass-intention attachment.
- **`api/app.py`** — thin FastAPI layer: routes, response models,
  ETags, cache headers. No business logic.

## Tests

```bash
PYTHONPATH=. python tests/test_views.py    # 15 tests, view logic
PYTHONPATH=. python tests/test_api.py      # 15 tests, HTTP layer
```

API tests use FastAPI's `TestClient` against a temporary SQLite DB
seeded with the hand-built reference bulletin — no API key, no
network.

---

# Roster Seeder

The seeder (`bulletin_parser.seeder`) discovers parishes from diocesan
directories and produces roster entries the harness can ingest. It's
the answer to "how do we go from one hand-curated parish to hundreds
without typing each one in?"

## Be honest about what this is

Diocesan parish directories are heterogeneous. Some dioceses publish a
machine-readable parish list; most publish HTML pages with idiosyncratic
markup; a few don't publish a directory at all. The seeder is structured
to acknowledge this:

- **dioceses.py** is a hand-curated list of US dioceses. Each entry
  declares its `parish_directory_url` and a `parish_directory_kind`
  (`html_list`, `sitemap`, `json_api`, `manual`, or `unknown`).
  Dioceses with `unknown` are recorded but skipped at scraping time
  until a human classifies them.

- **directory_scrapers.py** has a `GenericHtmlListScraper` that handles
  the common `<a href="...">Parish Name</a>` pattern with chrome
  filtering and dedup. For dioceses with custom-shaped HTML, the right
  answer is a per-diocese scraper subclass; the base class makes that
  trivial.

- **host_detector.py** is generic and reusable. Given any parish
  website URL, it figures out whether the parish uses ecatholic, LPi,
  Discover Mass, a generic /bulletins page, or none of the above.
  It's a two-stage detector — first the homepage for platform
  fingerprints, then probe candidate `/bulletins` paths.

- **orchestrator.py** pulls it together. For each diocese: fetch the
  directory, scrape it, detect each parish's host, emit a roster entry.
  Failures are recorded per-parish so one broken diocese doesn't break
  a seeding run.

## Quick start

```bash
# See which dioceses are configured and which need classification
python -m bulletin_parser.seeder list-dioceses

# Scrape one diocese and emit a roster JSON file
python -m bulletin_parser.seeder seed --diocese ny-new-york -o ny_roster.json

# Or write directly into a harness DB
python -m bulletin_parser.seeder ingest --diocese ny-new-york \
    --db harness.db --pdfs ./pdfs
```

## Pipeline

```
  diocese.parish_directory_url
            │
            ▼
   ┌────────────────────┐
   │ DirectoryScraper   │  ← per-format: html_list | sitemap | json_api
   └────────────────────┘
            │
            ▼
   list[ScrapedParish]
            │
            ▼
   ┌────────────────────┐
   │ HostDetector       │  ← inspect homepage; probe /bulletins on miss
   └────────────────────┘
            │
            ▼
   roster entry dict ──► Storage.add_parish(**entry)
```

## Adding a new diocese

The minimal workflow:

1. Find the diocese's parish directory page on its website.
2. Look at the HTML — is it a list of `<a>` tags pointing to parish
   websites? Then `parish_directory_kind="html_list"` and the
   `GenericHtmlListScraper` should handle it. Run a test seed to verify.
3. If the HTML is unusual (entries are in JSON embedded in JS, or the
   page is paginated, etc.), write a per-diocese scraper subclass and
   register it.
4. Add the diocese to `US_DIOCESES` in `dioceses.py`.

## Operating notes

- **The first run for a diocese is the most important one.** It tells
  you what fraction of parishes have a detectable bulletin host. A
  diocese where 80% of parishes are ecatholic or have a `/bulletins`
  page is ready to ingest. A diocese where 80% come back `unknown`
  needs either better host detection or a custom approach (the
  detector won't find a bulletin that's only emailed via Flocknote).

- **Unknown parishes are inserted as inactive.** The harness skips
  inactive parishes, so they accumulate without breaking anything.
  Periodically review them; many will become resolvable as you add
  more platform fingerprints to the detector.

- **The directory URL changes.** Dioceses redesign their websites.
  Treat `dioceses.py` as living config and re-verify periodically.

---

# Quality Evals

The eval system (`bulletin_parser.evals`) measures parser quality on a
hand-curated reference set so prompt changes can be evaluated objectively
instead of by feel. It's the answer to "did that prompt change make
things better or worse?"

## The model

```
EvalCase     - input text + expected Bulletin
EvalRun      - parser was run against every case; here are the results
RunDiff      - comparing two EvalRuns; here are the regressions
```

Each Bulletin field has its own comparator with semantics that match how
parishioners would actually care:

- **recurring_schedule** (weight 30): list-match by (weekday, time, location, kind);
  language and end_time checked per-slot. Missing or extra slots are full
  failures.
- **schedule_exceptions** (weight 15): list-match by (date, kind, service,
  location); description allowed to paraphrase.
- **mass_intentions** (weight 15): list-match by (date, time, normalized name);
  fuzzy text on intention_for; `is_deceased` flag is exact.
- **announcements** (weight 15): list-match by normalized title; body
  allowed to paraphrase heavily (threshold 0.5); priority within ±1
  scores full credit; ±2 partial.
- **liturgical_day** (8), **parish** (7), **collections** (5): see `checks.py`.

Weights are tuned for severity of regression. They sum to 95; the
remaining 5 is intentional headroom for fields we'll add later.

## CLI

```bash
# Show the current eval set
python -m bulletin_parser.evals list-cases

# Run all evals against the live parser (requires ANTHROPIC_API_KEY)
python -m bulletin_parser.evals run -o eval_runs/$(date +%Y%m%d).json

# After a prompt change, compare
python -m bulletin_parser.evals compare eval_runs/before.json eval_runs/after.json
```

`compare` exits non-zero if there are regressions, so CI can treat an
eval regression as a failed build.

## What the output looks like

A typical diff after a regression-introducing prompt change:

```
# Eval Diff: v1_baseline -> v2_regression

**Overall**: 100.00% -> 84.21%  (-15.79%) [REGRESSION]

## Regressions (1)

| Case                  | Field                 | Before  | After   | Delta     |
|---|---|---:|---:|---:|
| stpatricks_20260510   | schedule_exceptions   | 100.00% |   0.00% | -100.00%  |
```

One line tells you what regressed and by how much.

## Growing the eval set

`evals/cases.py` is where cases live. Adding one is a function that
returns an `EvalCase` with the source text and the expected Bulletin.
The St Patrick's case re-uses `build_stpatricks_reference()` from the
test suite — that's the hand-built ground truth.

For new cases: take a real bulletin, run the current parser, hand-edit
the output to fix any errors, save it as the expected. This is how the
ground truth grows. The right cadence is one new case per real parish
the system onboards.

## What the evals DON'T do

- They don't grade the parser against a single "right" answer. The
  comparators allow paraphrase, priority drift, name normalization
  variants. The point is to surface *real* disagreement, not to penalize
  reasonable variation.
- They don't catch bugs the eval set doesn't cover. The point of growing
  the set is that "we know X used to work" becomes durably true.
- They don't run automatically on the live parser. CI is the right place
  to add that — but evals cost API tokens, so think before turning on
  per-commit eval runs.

---

# Mobile App Shell

A PWA at `mobile_app/` consumes the API and renders the parishioner-facing
home view. Four screens (Today, Schedule, News, Settings), bottom-tab
navigation, offline-capable via service worker, mock-mode for development
without the backend.

```bash
cd mobile_app
npm install
npm run dev           # http://localhost:5173, mock data by default
npm run build         # static output in dist/
```

To point at a real API: copy `.env.example` to `.env.local` and set
`VITE_API_BASE_URL`.

See `mobile_app/README.md` for full details, including why a PWA was the
right choice for v1 (vs React Native or native) and what's deliberately
left out.

---

# Parish Search & Geocoding

The `/v1/parishes` endpoint now supports three search modes, backed by a
geocoded parish roster:

```
GET /v1/parishes?q=<text>                            — name/city/state search
GET /v1/parishes?postal_code=<zip>                   — ZIP / postal prefix
GET /v1/parishes?near=<lat>,<lng>&radius_km=<n>      — geographic search
```

Near-search returns parishes sorted by distance with `distance_km`
populated on each. Plain `GET /v1/parishes` (no params) still returns the
full active roster as before.

## Geocoding pipeline

Geocoding runs as a separate one-time-per-parish pipeline — NOT part of
weekly ingestion. Weekly bulletin fetching and one-time address lookup
have different cadences, different rate-limit profiles, and different
failure modes; conflating them was the wrong default.

```bash
# Geocode every parish that doesn't have coordinates yet
python -m bulletin_parser.seeder geocode --db harness.db --pdfs ./pdfs

# Retry parishes previously marked as failed (e.g. after fixing the address)
python -m bulletin_parser.seeder geocode --db harness.db --pdfs ./pdfs --retry-failed

# Limit to N parishes per run (rate-limit-friendly)
python -m bulletin_parser.seeder geocode --limit 100 ...
```

The default backend is **Nominatim** (OpenStreetMap), which is free and
requires no API key, but enforces a strict 1 req/sec rate limit. For a
roster of N parishes this takes roughly N seconds — a one-time cost per
parish, never re-run unless `--retry-failed`.

Production deployments wanting higher throughput should implement the
`Geocoder` protocol (`bulletin_parser.seeder.geocoder.Geocoder`) against
Mapbox, Google, or any other provider, and pass the instance into
`geocode_pending()`.

### Failure handling

The pipeline distinguishes hard failures ("no such place") from transient
failures (5xx, network errors). Hard failures set `geocode_failed=1` so
they aren't retried on every pass; transient failures leave the row
pending so the next run picks it up automatically.

## Schema migration

The `parishes` table grew columns: `address`, `postal_code`, `latitude`,
`longitude`, `geocoded_at`, `geocode_failed`. The migration is idempotent
and runs on every `Storage` construction — older DBs from before this
change pick up the new columns automatically the next time the harness
or API starts.

## Mobile app: Search

The PWA now has a **Search** screen with three modes: "Near me" (uses
the browser geolocation API), "ZIP / city", and "Name". The optional
map view (Leaflet + OpenStreetMap tiles) lets the user see pins; tapping
a pin selects that parish and routes to Today.

First-time users land directly on Search instead of the cold-start
default parish. The Settings screen exposes a "Change parish" button
that re-opens Search.

The map chunk is lazy-loaded (44KB gzipped) so the main bundle stays
small for users who never open it. With the map, the build is roughly
~100KB gzipped; without, ~54KB.

---

# Production Deployment

The repo ships with a complete single-VPS deployment story:

- `Dockerfile` — one image, used by both the API service and the
  weekly harness one-shot.
- `docker-compose.yml` — three services (caddy reverse proxy, api,
  harness as a one-shot).
- `Caddyfile` — automatic Let's Encrypt TLS, `/api/*` to FastAPI, static
  serve of the built PWA for everything else.
- `ops/` — operational shell scripts (backup, restore, status,
  cron-harness).
- `deploy/RUNBOOK.md` — the full operator runbook, from "fresh VPS" to
  "five parishioners are using it on Sunday morning."
- `.github/workflows/ci.yml` — runs tests on every push, builds and
  pushes a Docker image on tagged releases.

For a 5-user test deploy, you need:

1. A small VPS (~$5/mo on Hetzner or DigitalOcean)
2. A domain with DNS you control
3. An Anthropic API key
4. ~20 minutes

The full instructions live in `deploy/RUNBOOK.md`. Briefly:

```bash
# On the VPS:
git clone <repo> /opt/bulletin && cd /opt/bulletin
cp .env.example .env && $EDITOR .env       # set DOMAIN, ACME_EMAIL, API key
( cd mobile_app && npm ci && npm run build )
docker compose up -d --build

# Add a parish, geocode it, parse this week's bulletin:
docker compose run --rm --no-deps harness \
    python -m bulletin_parser.harness add-parish \
    --id ny-old-st-patricks --name "..." \
    --host-kind ecatholic --ecatholic-id 11778 \
    --diocese "..." --city "..." --state NY
docker compose run --rm --no-deps harness \
    python -m bulletin_parser.seeder geocode
docker compose run --rm harness
```

Set up weekly cron via `ops/cron-harness.sh`. Backup/restore via
`ops/backup.sh` and `ops/restore.sh`. Day-to-day check via
`ops/status.sh`.

## Ethics

We're fetching real bulletins from real parishes from a real CDN. The
fetcher is polite (1 req/sec/host, identifying User-Agent, respects
robots.txt). For each parish onboarded for real testing, email the
pastor or parish office to introduce the project. Friendly partnerships
beat scraping at scale.
