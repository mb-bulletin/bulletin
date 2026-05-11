"""
SQLite-backed storage for the ingestion harness.

Schema design:

  parishes              — the roster: which parishes to ingest, how to find their bulletins
  fetch_attempts        — one row per HTTP attempt, regardless of outcome (audit log)
  bulletins             — one row per *distinct* PDF we've successfully fetched (deduped by content hash)
  parsed_bulletins      — one row per parse of a bulletin (multiple parses possible across parser versions)

Why this split:
- Re-parsing old PDFs after a prompt improvement should NOT require re-fetching.
- A failed parse should NOT lose the PDF we paid bandwidth to fetch.
- The audit log needs to retain "we tried to fetch X at time Y and got 404"
  even when no bulletin was produced.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


SCHEMA = """
CREATE TABLE IF NOT EXISTS parishes (
    id              TEXT PRIMARY KEY,         -- our stable id, e.g. "ny-old-st-patricks"
    name            TEXT NOT NULL,
    diocese         TEXT,
    city            TEXT,
    state           TEXT,
    country         TEXT DEFAULT 'US',
    host_kind       TEXT NOT NULL,            -- 'ecatholic' | 'generic_html' | 'manual_url'
    ecatholic_id    TEXT,                     -- e.g. "11778" — only for host_kind='ecatholic'
    bulletins_url   TEXT,                     -- e.g. "https://stmargaretmary.org/bulletins" — for generic_html
    manual_url      TEXT,                     -- direct PDF URL — for manual_url
    timezone        TEXT DEFAULT 'America/New_York',
    active          INTEGER NOT NULL DEFAULT 1,
    notes           TEXT,
    added_at        TEXT NOT NULL,
    last_checked_at TEXT,
    -- Location columns: nullable because we backfill via the geocoder
    -- pipeline, not at parish-creation time.
    address         TEXT,
    postal_code     TEXT,
    latitude        REAL,
    longitude       REAL,
    geocoded_at     TEXT,
    geocode_failed  INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_parishes_active ON parishes(active);

CREATE TABLE IF NOT EXISTS fetch_attempts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    parish_id       TEXT NOT NULL REFERENCES parishes(id),
    attempted_at    TEXT NOT NULL,
    url             TEXT,
    outcome         TEXT NOT NULL,            -- 'new' | 'unchanged' | 'http_error' | 'not_found' | 'parse_error' | 'discovery_failed'
    http_status     INTEGER,
    bytes_fetched   INTEGER,
    bulletin_id     INTEGER REFERENCES bulletins(id),  -- set when outcome in ('new','unchanged')
    error_message   TEXT
);

CREATE INDEX IF NOT EXISTS idx_fetch_attempts_parish ON fetch_attempts(parish_id, attempted_at DESC);
CREATE INDEX IF NOT EXISTS idx_fetch_attempts_outcome ON fetch_attempts(outcome, attempted_at DESC);

CREATE TABLE IF NOT EXISTS bulletins (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    parish_id       TEXT NOT NULL REFERENCES parishes(id),
    content_sha256  TEXT NOT NULL,            -- hash of the PDF bytes
    pdf_path        TEXT NOT NULL,            -- relative path under the storage root
    pdf_url         TEXT NOT NULL,            -- where we fetched it from
    bytes           INTEGER NOT NULL,
    fetched_at      TEXT NOT NULL,
    UNIQUE(parish_id, content_sha256)
);

CREATE INDEX IF NOT EXISTS idx_bulletins_parish ON bulletins(parish_id, fetched_at DESC);

CREATE TABLE IF NOT EXISTS parsed_bulletins (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    bulletin_id     INTEGER NOT NULL REFERENCES bulletins(id),
    parser_version  TEXT NOT NULL,
    model           TEXT NOT NULL,
    parsed_at       TEXT NOT NULL,
    payload_json    TEXT,                     -- the full Bulletin JSON; NULL when parse_error set
    tokens_in       INTEGER,
    tokens_out      INTEGER,
    parse_error     TEXT,                     -- set if parsing failed; payload_json may then be partial/null
    UNIQUE(bulletin_id, parser_version, model)
);

CREATE INDEX IF NOT EXISTS idx_parsed_bulletin ON parsed_bulletins(bulletin_id);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Storage:
    """SQLite store for the ingestion harness."""

    def __init__(self, db_path: str | Path, pdf_root: str | Path):
        self.db_path = Path(db_path)
        self.pdf_root = Path(pdf_root)
        self.pdf_root.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            self._migrate_parishes_columns(conn)

    def _migrate_parishes_columns(self, conn: sqlite3.Connection) -> None:
        """Idempotently add columns that may be missing on older DBs.

        SQLite doesn't have IF NOT EXISTS for ADD COLUMN, so we introspect
        the table and add what's missing. New columns we want everywhere:
          - address, postal_code, latitude, longitude (geocoding)
          - geocoded_at, geocode_failed (geocoding pipeline state)
        """
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(parishes)")}
        for col, ddl in [
            ("address",        "ADD COLUMN address TEXT"),
            ("postal_code",    "ADD COLUMN postal_code TEXT"),
            ("latitude",       "ADD COLUMN latitude REAL"),
            ("longitude",      "ADD COLUMN longitude REAL"),
            ("geocoded_at",    "ADD COLUMN geocoded_at TEXT"),
            ("geocode_failed", "ADD COLUMN geocode_failed INTEGER DEFAULT 0"),
        ]:
            if col not in cols:
                conn.execute(f"ALTER TABLE parishes {ddl}")

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        try:
            yield conn
        finally:
            conn.close()

    # ---- Parish roster ----

    def add_parish(self, **kwargs: Any) -> None:
        kwargs.setdefault("added_at", now_iso())
        with self.connect() as conn:
            cols = ", ".join(kwargs.keys())
            placeholders = ", ".join(f":{k}" for k in kwargs)
            conn.execute(
                f"INSERT OR REPLACE INTO parishes ({cols}) VALUES ({placeholders})",
                kwargs,
            )

    def list_active_parishes(self) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return list(conn.execute(
                "SELECT * FROM parishes WHERE active=1 ORDER BY id"
            ))

    def mark_checked(self, parish_id: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE parishes SET last_checked_at=? WHERE id=?",
                (now_iso(), parish_id),
            )

    # ---- Fetch attempts ----

    def log_attempt(
        self,
        parish_id: str,
        outcome: str,
        *,
        url: str | None = None,
        http_status: int | None = None,
        bytes_fetched: int | None = None,
        bulletin_id: int | None = None,
        error_message: str | None = None,
    ) -> int:
        with self.connect() as conn:
            cur = conn.execute(
                """INSERT INTO fetch_attempts
                   (parish_id, attempted_at, url, outcome, http_status,
                    bytes_fetched, bulletin_id, error_message)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (parish_id, now_iso(), url, outcome, http_status,
                 bytes_fetched, bulletin_id, error_message),
            )
            return cur.lastrowid  # type: ignore[return-value]

    # ---- Bulletins (PDFs) ----

    def find_bulletin_by_hash(
        self, parish_id: str, content_sha256: str
    ) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM bulletins WHERE parish_id=? AND content_sha256=?",
                (parish_id, content_sha256),
            ).fetchone()

    def save_bulletin(
        self,
        parish_id: str,
        content_sha256: str,
        pdf_bytes: bytes,
        pdf_url: str,
    ) -> tuple[int, Path]:
        """Save a PDF to disk and record it in the DB. Returns (bulletin_id, path)."""
        # Path layout: pdf_root / parish_id / YYYY / sha-prefix-filename.pdf
        ts = datetime.now(timezone.utc)
        rel_dir = Path(parish_id) / str(ts.year)
        rel_path = rel_dir / f"{content_sha256[:12]}.pdf"
        abs_path = self.pdf_root / rel_path
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_bytes(pdf_bytes)

        with self.connect() as conn:
            cur = conn.execute(
                """INSERT INTO bulletins
                   (parish_id, content_sha256, pdf_path, pdf_url, bytes, fetched_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (parish_id, content_sha256, str(rel_path), pdf_url,
                 len(pdf_bytes), now_iso()),
            )
            return cur.lastrowid, abs_path  # type: ignore[return-value]

    def abs_pdf_path(self, rel_path: str) -> Path:
        return self.pdf_root / rel_path

    # ---- Parsed bulletins ----

    def save_parse(
        self,
        bulletin_id: int,
        parser_version: str,
        model: str,
        payload: dict | None,
        *,
        tokens_in: int | None = None,
        tokens_out: int | None = None,
        parse_error: str | None = None,
    ) -> int:
        with self.connect() as conn:
            cur = conn.execute(
                """INSERT OR REPLACE INTO parsed_bulletins
                   (bulletin_id, parser_version, model, parsed_at,
                    payload_json, tokens_in, tokens_out, parse_error)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (bulletin_id, parser_version, model, now_iso(),
                 json.dumps(payload) if payload else None,
                 tokens_in, tokens_out, parse_error),
            )
            return cur.lastrowid  # type: ignore[return-value]

    def latest_parse(self, bulletin_id: int) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute(
                """SELECT * FROM parsed_bulletins
                   WHERE bulletin_id=?
                   ORDER BY parsed_at DESC LIMIT 1""",
                (bulletin_id,),
            ).fetchone()

    # ---- Reporting ----

    def recent_attempts(self, limit: int = 50) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return list(conn.execute(
                """SELECT fa.*, p.name AS parish_name
                   FROM fetch_attempts fa
                   JOIN parishes p ON p.id = fa.parish_id
                   ORDER BY attempted_at DESC LIMIT ?""",
                (limit,),
            ))

    def health_summary(self) -> dict[str, Any]:
        """Stats for the last 7 days, for monitoring dashboards."""
        with self.connect() as conn:
            row = conn.execute("""
                SELECT
                  COUNT(*) AS attempts,
                  SUM(CASE WHEN outcome='new' THEN 1 ELSE 0 END) AS new_bulletins,
                  SUM(CASE WHEN outcome='unchanged' THEN 1 ELSE 0 END) AS unchanged,
                  SUM(CASE WHEN outcome IN ('http_error','not_found','discovery_failed','parse_error')
                           THEN 1 ELSE 0 END) AS errors
                FROM fetch_attempts
                WHERE attempted_at > datetime('now', '-7 days')
            """).fetchone()
            return dict(row) if row else {}
