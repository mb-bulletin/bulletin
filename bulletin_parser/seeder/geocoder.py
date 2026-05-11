"""
Geocoder pipeline.

Turns parish address strings into (lat, lng) coordinates and writes them
back to the parishes table. Designed as a separate one-time-per-parish
pipeline, NOT as part of weekly ingestion — geocoding and bulletin
fetching have different cadences and different failure modes.

Backend choice:
  - Default: Nominatim (OpenStreetMap) via HTTPS. Free, no API key,
    strict 1 req/sec rate limit per their usage policy.
  - Pluggable: pass any `Geocoder` instance to `geocode_pending` for
    production deployments that need higher throughput (Mapbox, Google).

Failure handling:
  - A parish that fails to geocode gets `geocode_failed=1` so we don't
    retry every run. The CLI has a `--retry-failed` flag for the cases
    where we fixed the address or the upstream changed.
  - Pure 404-style "no match" failures still set geocode_failed=1; only
    transient HTTP errors (5xx, connection error) leave the row pending
    for next time.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Iterable, Protocol
from urllib.parse import quote

import requests


log = logging.getLogger(__name__)

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"


@dataclass(frozen=True)
class GeocodeResult:
    latitude: float
    longitude: float
    matched_address: str | None = None  # what the geocoder thought we asked for


class GeocodeError(Exception):
    """Geocoder didn't get a usable result. `transient` distinguishes
    network/server hiccups (retry) from "no such place" (mark failed)."""

    def __init__(self, message: str, *, transient: bool = False):
        super().__init__(message)
        self.transient = transient


class Geocoder(Protocol):
    def geocode(self, address: str) -> GeocodeResult: ...


class NominatimGeocoder:
    """OpenStreetMap Nominatim. Rate-limited to 1 req/sec per their TOS."""

    def __init__(
        self,
        *,
        user_agent: str = "BulletinParserBot/0.1 (contact@example.org)",
        delay_s: float = 1.1,  # be a hair over the 1 req/s limit
        timeout_s: float = 10.0,
    ):
        self.user_agent = user_agent
        self.delay_s = delay_s
        self.timeout_s = timeout_s
        self._last_call = 0.0
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": user_agent})

    def _wait(self) -> None:
        elapsed = time.monotonic() - self._last_call
        if elapsed < self.delay_s:
            time.sleep(self.delay_s - elapsed)
        self._last_call = time.monotonic()

    def geocode(self, address: str) -> GeocodeResult:
        if not address.strip():
            raise GeocodeError("empty address", transient=False)
        self._wait()
        params = {"q": address, "format": "json", "limit": "1", "addressdetails": "0"}
        url = f"{NOMINATIM_URL}?" + "&".join(f"{k}={quote(v)}" for k, v in params.items())
        try:
            resp = self._session.get(url, timeout=self.timeout_s)
        except requests.RequestException as e:
            raise GeocodeError(f"network: {e}", transient=True) from e
        if resp.status_code >= 500:
            raise GeocodeError(f"server {resp.status_code}", transient=True)
        if resp.status_code != 200:
            raise GeocodeError(f"http {resp.status_code}", transient=False)
        try:
            data = resp.json()
        except ValueError as e:
            raise GeocodeError(f"non-JSON response: {e}", transient=True) from e
        if not data:
            raise GeocodeError("no match", transient=False)
        first = data[0]
        return GeocodeResult(
            latitude=float(first["lat"]),
            longitude=float(first["lon"]),
            matched_address=first.get("display_name"),
        )


# ---- Pipeline ------------------------------------------------------------


def _build_query(parish_row) -> str:
    """Construct the best query string we can from a parish row.

    Prefer `address` if set. Otherwise fall back to "Name, City, State"
    which works surprisingly well for famous parishes ("Basilica of
    St. Patrick's Old Cathedral, New York, NY").
    """
    addr = parish_row["address"]
    if addr:
        return addr
    parts = [parish_row["name"]]
    if parish_row["city"]:
        parts.append(parish_row["city"])
    if parish_row["state"]:
        parts.append(parish_row["state"])
    return ", ".join(parts)


def geocode_pending(
    storage,
    *,
    geocoder: Geocoder | None = None,
    limit: int | None = None,
    retry_failed: bool = False,
) -> dict[str, int]:
    """Geocode every parish that needs it. Returns a stats dict.

    Stats keys: 'geocoded' (new successes), 'already_done', 'failed_hard'
    (no match found), 'failed_transient' (network/5xx, will retry).
    """
    geocoder = geocoder or NominatimGeocoder()
    stats = {"geocoded": 0, "already_done": 0, "failed_hard": 0, "failed_transient": 0}

    with storage.connect() as conn:
        where = "WHERE latitude IS NULL"
        if not retry_failed:
            where += " AND (geocode_failed IS NULL OR geocode_failed = 0)"
        sql = f"SELECT * FROM parishes {where}"
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
        rows = list(conn.execute(sql))

    for row in rows:
        query = _build_query(row)
        try:
            result = geocoder.geocode(query)
        except GeocodeError as e:
            if e.transient:
                log.warning("transient geocode failure for %s: %s", row["id"], e)
                stats["failed_transient"] += 1
                continue
            log.info("hard geocode failure for %s: %s", row["id"], e)
            with storage.connect() as conn:
                conn.execute(
                    "UPDATE parishes SET geocode_failed=1, geocoded_at=? WHERE id=?",
                    (_now_iso(), row["id"]),
                )
            stats["failed_hard"] += 1
            continue

        log.info("geocoded %s: %s, %s", row["id"], result.latitude, result.longitude)
        with storage.connect() as conn:
            conn.execute(
                """UPDATE parishes
                   SET latitude=?, longitude=?, geocoded_at=?, geocode_failed=0
                   WHERE id=?""",
                (result.latitude, result.longitude, _now_iso(), row["id"]),
            )
        stats["geocoded"] += 1

    return stats


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
