"""
Seeder CLI.

Subcommands:
  list-dioceses          — show known dioceses and their readiness
  seed                   — scrape one or more dioceses and emit roster JSON
  ingest                 — same as seed, but write directly into a harness DB

Examples:
  python -m bulletin_parser.seeder list-dioceses
  python -m bulletin_parser.seeder seed --diocese ny-new-york -o ny_roster.json
  python -m bulletin_parser.seeder seed --state NY -o ny_roster.json
  python -m bulletin_parser.seeder ingest --diocese ny-new-york \\
      --db harness.db --pdfs ./pdfs
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from ..harness.fetcher import Fetcher
from ..harness.storage import Storage
from .dioceses import US_DIOCESES, by_id, by_state, with_directory
from .orchestrator import Seeder, SeedingReport


def cmd_list_dioceses(args) -> int:
    print(f"{'ID':<24} {'Kind':<12} {'State':<6} {'Name'}")
    for d in US_DIOCESES:
        kind = d.parish_directory_kind
        marker = " " if kind != "unknown" else "*"
        print(f"{d.id:<24} {kind:<12} {d.state:<6} {marker} {d.name}")
    print()
    print(f"{len(US_DIOCESES)} dioceses; "
          f"{len(with_directory())} scrapeable; "
          f"{len(US_DIOCESES) - len(with_directory())} need classification (*)")
    return 0


def _selected_dioceses(args):
    if args.diocese:
        d = by_id(args.diocese)
        return [d] if d else []
    if args.state:
        return by_state(args.state)
    if args.all:
        return list(US_DIOCESES)
    return []


def _print_report(r: SeedingReport) -> None:
    print(f"  {r.diocese_id}:")
    print(f"    scraped:           {r.scraped}")
    print(f"    ecatholic:         {r.detected_ecatholic}")
    print(f"    generic_html:      {r.detected_generic_html}")
    print(f"    other:             {r.detected_other}")
    print(f"    unknown:           {r.detected_unknown}")
    for err in r.errors:
        print(f"    error:             {err}")


def cmd_seed(args) -> int:
    dioceses = _selected_dioceses(args)
    if not dioceses:
        print("No dioceses selected. Pass --diocese, --state, or --all.", file=sys.stderr)
        return 2

    seeder = Seeder()
    all_entries: list[dict] = []
    for d in dioceses:
        entries, report = seeder.seed_diocese(d)
        _print_report(report)
        all_entries.extend(entries)

    if args.output:
        Path(args.output).write_text(
            json.dumps(all_entries, indent=2, default=str)
        )
        print(f"\nWrote {len(all_entries)} roster entries to {args.output}")
    else:
        print()
        json.dump(all_entries, sys.stdout, indent=2, default=str)
        print()
    return 0


def cmd_ingest(args) -> int:
    """Seed dioceses AND insert results directly into the harness DB."""
    dioceses = _selected_dioceses(args)
    if not dioceses:
        print("No dioceses selected. Pass --diocese, --state, or --all.", file=sys.stderr)
        return 2

    storage = Storage(args.db, args.pdfs)
    seeder = Seeder()
    inserted = 0
    for d in dioceses:
        entries, report = seeder.seed_diocese(d)
        _print_report(report)
        for entry in entries:
            # Only insert parishes we can actually fetch from; mark
            # 'unknown' parishes inactive so the harness skips them.
            if entry.get("host_kind") == "unknown":
                entry["active"] = 0
            storage.add_parish(**{k: v for k, v in entry.items() if k != "_provenance"})
            inserted += 1
    print(f"\nInserted/updated {inserted} parishes into {args.db}")
    return 0


def cmd_geocode(args) -> int:
    """Geocode parishes that don't have coordinates yet.

    Uses Nominatim (OSM) by default, which is rate-limited to ~1 req/s.
    For a roster of N parishes this takes roughly N seconds, so it's a
    one-time-per-parish cost. Failures are recorded so they aren't
    retried automatically; pass --retry-failed to give them another try.
    """
    from .geocoder import geocode_pending

    storage = Storage(args.db, args.pdfs)
    stats = geocode_pending(
        storage,
        limit=args.limit,
        retry_failed=args.retry_failed,
    )
    print("Geocode pass complete:")
    print(f"  geocoded:           {stats['geocoded']}")
    print(f"  failed (no match):  {stats['failed_hard']}")
    print(f"  failed (transient): {stats['failed_transient']}")
    return 0 if stats["failed_transient"] == 0 else 2


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("list-dioceses")
    s.set_defaults(func=cmd_list_dioceses)

    for name, fn in [("seed", cmd_seed), ("ingest", cmd_ingest)]:
        s = sub.add_parser(name)
        s.add_argument("--diocese", help="Diocese id (see list-dioceses)")
        s.add_argument("--state", help="All dioceses in this state")
        s.add_argument("--all", action="store_true", help="All known dioceses")
        if name == "seed":
            s.add_argument("-o", "--output", help="Path to write roster JSON")
        else:
            s.add_argument("--db", default="harness.db")
            s.add_argument("--pdfs", default="pdfs")
        s.set_defaults(func=fn)

    s = sub.add_parser("geocode", help="Geocode parishes missing coordinates")
    s.add_argument("--db", default="harness.db")
    s.add_argument("--pdfs", default="pdfs")
    s.add_argument("--limit", type=int, help="Stop after N parishes")
    s.add_argument("--retry-failed", action="store_true",
                   help="Also retry parishes previously marked as geocode_failed")
    s.set_defaults(func=cmd_geocode)

    args = p.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
