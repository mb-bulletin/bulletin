"""
Repository layer: pure data access over the harness storage.

The API uses this; the API never touches SQLite directly. That separation
means: (a) we can swap SQLite for Postgres later by changing one file,
(b) the repository is testable without HTTP, and (c) the harness and API
share the same data primitives.

Repository methods return domain objects (Bulletin from the parser
schema, or small dataclasses defined here for things the parser doesn't
model — e.g. ParishSummary). They do NOT return raw sqlite3.Row objects;
that detail stays inside this module.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterator

from ..harness.storage import Storage
from ..schema import Bulletin


@dataclass(frozen=True)
class ParishSummary:
    """Lightweight parish info for listings; doesn't include the bulletin."""
    id: str
    name: str
    diocese: str | None
    city: str | None
    state: str | None
    country: str
    timezone: str
    active: bool
    address: str | None = None
    postal_code: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    # Only set when the parish was returned by a /parishes?near=... query;
    # the API layer attaches this from the haversine calc.
    distance_km: float | None = None


@dataclass(frozen=True)
class BulletinRecord:
    """A parsed bulletin plus the storage metadata around it.

    Surfaces the content hash (for ETags) and the bulletin's fetched_at
    timestamp (for Last-Modified) without forcing every endpoint to also
    do its own DB joins.
    """
    parish_id: str
    bulletin: Bulletin
    content_sha256: str
    fetched_at: datetime  # the underlying PDF's fetched_at
    parsed_at: datetime


class Repository:
    """Read-only data access for the API.

    Reads only — writes happen through the harness. Constructed once at
    application startup and shared across requests; SQLite connections
    are per-request (acquired via the Storage context manager).
    """

    def __init__(self, storage: Storage):
        self.storage = storage

    # ---- Parishes ----

    def get_parish(self, parish_id: str) -> ParishSummary | None:
        with self.storage.connect() as conn:
            row = conn.execute(
                "SELECT * FROM parishes WHERE id=?", (parish_id,)
            ).fetchone()
        return _row_to_parish(row) if row else None

    def list_parishes(
        self, *, active_only: bool = True, limit: int | None = None
    ) -> list[ParishSummary]:
        sql = "SELECT * FROM parishes"
        if active_only:
            sql += " WHERE active=1"
        sql += " ORDER BY id"
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
        with self.storage.connect() as conn:
            return [_row_to_parish(r) for r in conn.execute(sql)]

    # ---- Search ----
    #
    # Three modes, exposed by /v1/parishes via query params. We do simple
    # SQL LIKE for text/postal; geographic search uses an in-memory
    # haversine pass over active parishes with coordinates. For the
    # parish count we expect (thousands, not millions), this is fast
    # enough. If it ever isn't, add a spatial index — but it isn't yet.

    def search_by_text(self, q: str, *, limit: int = 25) -> list[ParishSummary]:
        """Match against parish name, city, or state. Case-insensitive."""
        # SQLite LIKE is case-insensitive for ASCII by default; we don't
        # do anything fancy for unicode-case-folded matching here.
        q = q.strip()
        if not q:
            return []
        like = f"%{q}%"
        with self.storage.connect() as conn:
            rows = conn.execute(
                """SELECT * FROM parishes
                   WHERE active=1 AND (
                     name LIKE ? OR city LIKE ? OR state LIKE ?
                   )
                   ORDER BY name LIMIT ?""",
                (like, like, like, limit),
            ).fetchall()
        return [_row_to_parish(r) for r in rows]

    def search_by_postal_code(
        self, postal_code: str, *, limit: int = 25
    ) -> list[ParishSummary]:
        pc = postal_code.strip()
        if not pc:
            return []
        # Exact-prefix match; ZIP "10012" matches both "10012" and
        # "10012-1234" style values.
        with self.storage.connect() as conn:
            rows = conn.execute(
                """SELECT * FROM parishes
                   WHERE active=1 AND postal_code LIKE ?
                   ORDER BY name LIMIT ?""",
                (f"{pc}%", limit),
            ).fetchall()
        return [_row_to_parish(r) for r in rows]

    def search_by_location(
        self, lat: float, lng: float, *, radius_km: float = 25, limit: int = 25
    ) -> list[ParishSummary]:
        """Parishes within radius_km of (lat, lng), nearest first.

        Returns ParishSummary objects with distance_km populated. Filters
        out parishes that haven't been geocoded yet.
        """
        with self.storage.connect() as conn:
            rows = conn.execute(
                """SELECT * FROM parishes
                   WHERE active=1
                     AND latitude IS NOT NULL
                     AND longitude IS NOT NULL"""
            ).fetchall()

        from dataclasses import replace
        out: list[ParishSummary] = []
        for r in rows:
            p = _row_to_parish(r)
            if p.latitude is None or p.longitude is None:
                continue
            d = _haversine_km(lat, lng, p.latitude, p.longitude)
            if d <= radius_km:
                out.append(replace(p, distance_km=d))
        out.sort(key=lambda p: p.distance_km or float("inf"))
        return out[:limit]

    # ---- Bulletins ----

    def get_current_bulletin(self, parish_id: str) -> BulletinRecord | None:
        """Latest successfully-parsed bulletin for the parish."""
        with self.storage.connect() as conn:
            row = conn.execute(
                """SELECT b.parish_id, b.content_sha256, b.fetched_at,
                          p.parsed_at, p.payload_json
                   FROM bulletins b
                   JOIN parsed_bulletins p ON p.bulletin_id = b.id
                   WHERE b.parish_id = ? AND p.payload_json IS NOT NULL
                   ORDER BY b.fetched_at DESC, p.parsed_at DESC
                   LIMIT 1""",
                (parish_id,),
            ).fetchone()
        return _row_to_bulletin_record(row) if row else None

    def get_bulletin_for_date(
        self, parish_id: str, week_starting: date
    ) -> BulletinRecord | None:
        """The bulletin published for a specific Sunday."""
        # We can't query by week_starting in SQL directly because that lives
        # inside the JSON payload. For modest data volumes this is fine; if
        # we ever need scale, lift week_starting into a column.
        with self.storage.connect() as conn:
            rows = conn.execute(
                """SELECT b.parish_id, b.content_sha256, b.fetched_at,
                          p.parsed_at, p.payload_json
                   FROM bulletins b
                   JOIN parsed_bulletins p ON p.bulletin_id = b.id
                   WHERE b.parish_id = ? AND p.payload_json IS NOT NULL
                   ORDER BY b.fetched_at DESC""",
                (parish_id,),
            ).fetchall()
        for r in rows:
            payload = json.loads(r["payload_json"])
            if payload.get("week_starting") == week_starting.isoformat():
                return _row_to_bulletin_record(r)
        return None

    def list_bulletins(
        self, parish_id: str, *, limit: int = 20
    ) -> Iterator[BulletinRecord]:
        with self.storage.connect() as conn:
            rows = conn.execute(
                """SELECT b.parish_id, b.content_sha256, b.fetched_at,
                          p.parsed_at, p.payload_json
                   FROM bulletins b
                   JOIN parsed_bulletins p ON p.bulletin_id = b.id
                   WHERE b.parish_id = ? AND p.payload_json IS NOT NULL
                   ORDER BY b.fetched_at DESC LIMIT ?""",
                (parish_id, limit),
            ).fetchall()
        for r in rows:
            rec = _row_to_bulletin_record(r)
            if rec:
                yield rec


# ---- Row mappers (kept local; not part of the public interface) ----

def _row_to_parish(row) -> ParishSummary:
    # Use dict-style access for nullable columns that may be absent on
    # legacy DBs where the migration didn't run.
    def maybe(key):
        try:
            return row[key]
        except (KeyError, IndexError):
            return None
    return ParishSummary(
        id=row["id"],
        name=row["name"],
        diocese=row["diocese"],
        city=row["city"],
        state=row["state"],
        country=row["country"] or "US",
        timezone=row["timezone"] or "America/New_York",
        active=bool(row["active"]),
        address=maybe("address"),
        postal_code=maybe("postal_code"),
        latitude=maybe("latitude"),
        longitude=maybe("longitude"),
    )


def _row_to_bulletin_record(row) -> BulletinRecord | None:
    payload = row["payload_json"]
    if not payload:
        return None
    bulletin = Bulletin.model_validate_json(payload)
    return BulletinRecord(
        parish_id=row["parish_id"],
        bulletin=bulletin,
        content_sha256=row["content_sha256"],
        fetched_at=_parse_iso(row["fetched_at"]),
        parsed_at=_parse_iso(row["parsed_at"]),
    )


def _parse_iso(s: str) -> datetime:
    # Stored ISO 8601, possibly with offset. fromisoformat handles both.
    return datetime.fromisoformat(s)


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in kilometers between two lat/lng points."""
    from math import asin, cos, radians, sin, sqrt
    r = 6371.0  # Earth's mean radius
    phi1, phi2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dlambda = radians(lng2 - lng1)
    a = sin(dphi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(dlambda / 2) ** 2
    return 2 * r * asin(sqrt(a))
