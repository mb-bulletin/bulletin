"""
Harness CLI.

Subcommands:
  init                — create the SQLite DB and roster from a JSON/CSV file
  add-parish          — add a single parish to the roster
  list-parishes       — show the active roster
  run                 — run one ingestion pass over the active roster
  status              — print health summary and recent attempts
  reparse             — re-parse stored PDFs (e.g., after prompt improvements)

Cron usage:
  0 18 * * SAT  python -m bulletin_parser.harness run --db ./harness.db --pdfs ./pdfs
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from pathlib import Path

from .orchestrator import Orchestrator
from .fetcher import Fetcher
from .storage import Storage


def setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def cmd_init(args) -> int:
    storage = Storage(args.db, args.pdfs)
    print(f"Initialized DB at {args.db}, PDFs at {args.pdfs}")
    if args.roster:
        added = _load_roster(storage, args.roster)
        print(f"Loaded {added} parishes from {args.roster}")
    return 0


def _load_roster(storage: Storage, path: str) -> int:
    p = Path(path)
    if p.suffix == ".json":
        rows = json.loads(p.read_text())
    elif p.suffix == ".csv":
        with p.open() as f:
            rows = list(csv.DictReader(f))
    else:
        raise SystemExit(f"Roster must be .json or .csv, got {p.suffix}")
    for r in rows:
        # Normalize: empty strings -> None; "active" string -> int
        clean = {k: (v if v != "" else None) for k, v in r.items()}
        if "active" in clean and clean["active"] is not None:
            clean["active"] = int(clean["active"])
        storage.add_parish(**clean)
    return len(rows)


def cmd_add_parish(args) -> int:
    storage = Storage(args.db, args.pdfs)
    storage.add_parish(
        id=args.id, name=args.name, host_kind=args.host_kind,
        ecatholic_id=args.ecatholic_id, bulletins_url=args.bulletins_url,
        manual_url=args.manual_url, diocese=args.diocese,
        city=args.city, state=args.state, active=1,
    )
    print(f"Added parish: {args.id}")
    return 0


def cmd_list_parishes(args) -> int:
    storage = Storage(args.db, args.pdfs)
    for p in storage.list_active_parishes():
        print(f"  {p['id']:<35} {p['host_kind']:<14} {p['name']}")
    return 0


def cmd_run(args) -> int:
    storage = Storage(args.db, args.pdfs)
    fetcher = Fetcher(
        per_host_delay_s=args.delay,
        respect_robots=not args.ignore_robots,
    )
    orch = Orchestrator(
        storage, fetcher,
        max_workers=args.workers, skip_parse=args.skip_parse, model=args.model,
    )
    stats = orch.run_once()
    print(f"Ingestion complete:")
    print(f"  parishes checked:   {stats.parishes_checked}")
    print(f"  new bulletins:      {stats.new_bulletins}")
    print(f"  unchanged:          {stats.unchanged}")
    print(f"  discovery failed:   {stats.discovery_failed}")
    print(f"  fetch errors:       {stats.fetch_errors}")
    print(f"  parse errors:       {stats.parse_errors}")
    return 0 if (stats.fetch_errors + stats.parse_errors) == 0 else 2


def cmd_status(args) -> int:
    storage = Storage(args.db, args.pdfs)
    h = storage.health_summary()
    print(f"Last 7 days:")
    print(f"  attempts:       {h.get('attempts') or 0}")
    print(f"  new bulletins:  {h.get('new_bulletins') or 0}")
    print(f"  unchanged:      {h.get('unchanged') or 0}")
    print(f"  errors:         {h.get('errors') or 0}")
    print()
    print(f"Recent attempts (last {args.recent}):")
    for a in storage.recent_attempts(limit=args.recent):
        bits = [a["attempted_at"], f"{a['outcome']:<16}", a["parish_name"][:40]]
        if a["error_message"]:
            bits.append(f"err={a['error_message'][:60]}")
        print("  " + "  ".join(bits))
    return 0


def cmd_reparse(args) -> int:
    """Re-run the parser on already-stored PDFs."""
    from ..extract import extract_text_from_pdf
    from ..parser import parse_bulletin

    storage = Storage(args.db, args.pdfs)
    with storage.connect() as conn:
        rows = list(conn.execute(
            "SELECT * FROM bulletins ORDER BY fetched_at DESC LIMIT ?",
            (args.limit,),
        ))
    print(f"Reparsing {len(rows)} bulletins with model={args.model} ...")
    for b in rows:
        pdf_path = storage.abs_pdf_path(b["pdf_path"])
        try:
            text = extract_text_from_pdf(pdf_path)
            bulletin = parse_bulletin(text, model=args.model)
            storage.save_parse(
                b["id"], parser_version=bulletin.parser_version,
                model=args.model, payload=bulletin.model_dump(mode="json"),
            )
            print(f"  ✓ {b['parish_id']}  {pdf_path.name}")
        except Exception as e:
            storage.save_parse(
                b["id"], parser_version="unknown",
                model=args.model, payload=None,
                parse_error=f"{type(e).__name__}: {e}",
            )
            print(f"  ✗ {b['parish_id']}  {pdf_path.name}  ({e})")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Bulletin ingestion harness")
    p.add_argument("--db", default="harness.db", help="SQLite DB path")
    p.add_argument("--pdfs", default="pdfs", help="Directory for stored PDFs")
    p.add_argument("-v", "--verbose", action="store_true")

    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="Initialize DB and load roster")
    s.add_argument("--roster", help="Path to roster .json or .csv")
    s.set_defaults(func=cmd_init)

    s = sub.add_parser("add-parish")
    s.add_argument("--id", required=True)
    s.add_argument("--name", required=True)
    s.add_argument("--host-kind", required=True,
                   choices=["ecatholic", "generic_html", "manual_url"])
    s.add_argument("--ecatholic-id")
    s.add_argument("--bulletins-url")
    s.add_argument("--manual-url")
    s.add_argument("--diocese")
    s.add_argument("--city")
    s.add_argument("--state")
    s.set_defaults(func=cmd_add_parish)

    s = sub.add_parser("list-parishes")
    s.set_defaults(func=cmd_list_parishes)

    s = sub.add_parser("run", help="Run one ingestion pass")
    s.add_argument("--workers", type=int, default=4)
    s.add_argument("--delay", type=float, default=1.0,
                   help="Min seconds between requests to the same host")
    s.add_argument("--ignore-robots", action="store_true",
                   help="Skip robots.txt checks (don't use unless you have reason)")
    s.add_argument("--skip-parse", action="store_true",
                   help="Fetch and store PDFs but don't call the parser")
    s.add_argument("--model", default="claude-opus-4-5")
    s.set_defaults(func=cmd_run)

    s = sub.add_parser("status")
    s.add_argument("--recent", type=int, default=20)
    s.set_defaults(func=cmd_status)

    s = sub.add_parser("reparse", help="Re-parse stored PDFs")
    s.add_argument("--limit", type=int, default=100)
    s.add_argument("--model", default="claude-opus-4-5")
    s.set_defaults(func=cmd_reparse)

    args = p.parse_args(argv)
    setup_logging(args.verbose)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
