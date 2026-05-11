"""
US Catholic dioceses — the entry point to parish discovery.

This is a small, hand-curated list to start. The full ~196 US dioceses
can be added incrementally; what matters for the seeder is that each
entry knows (a) its name and (b) the URL of its parish directory.

Format: a list of Diocese records. The `parish_directory_url` is the
page that lists this diocese's parishes — that's where the
per-diocese scraper starts. `parish_directory_kind` tells the seeder
which scraping strategy to use.

To add a diocese: figure out where its parish directory lives, identify
the strategy (a scraper class, or `unknown` for now), add an entry.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


DirectoryKind = Literal[
    "html_list",       # plain HTML page with a list of parishes
    "json_api",        # diocese exposes a JSON endpoint
    "sitemap",         # parish list lives in /sitemap.xml
    "manual",          # no automated source; humans add parishes
    "unknown",         # we haven't classified yet
]


@dataclass(frozen=True)
class Diocese:
    id: str                              # our stable slug, e.g. "ny-new-york"
    name: str                            # e.g. "Archdiocese of New York"
    state: str                           # primary state (some dioceses span multiple)
    website: str                         # the diocesan website
    parish_directory_url: str | None     # the page listing parishes; None if not yet known
    parish_directory_kind: DirectoryKind = "unknown"
    notes: str = ""


# Seed list. Expand incrementally; do not aim for completeness in one pass.
# The pattern is: pick a diocese, find its parish directory page, classify it.
# When `parish_directory_kind` is "unknown" the seeder still records the
# diocese but cannot enumerate its parishes automatically.
US_DIOCESES: list[Diocese] = [
    Diocese(
        id="ny-new-york",
        name="Archdiocese of New York",
        state="NY",
        website="https://archny.org",
        parish_directory_url="https://archny.org/parishes/",
        parish_directory_kind="html_list",
        notes="Covers Manhattan, Bronx, Staten Island, and several northern counties.",
    ),
    Diocese(
        id="ny-brooklyn",
        name="Diocese of Brooklyn",
        state="NY",
        website="https://dioceseofbrooklyn.org",
        parish_directory_url="https://dioceseofbrooklyn.org/parishes/",
        parish_directory_kind="html_list",
        notes="Brooklyn and Queens.",
    ),
    Diocese(
        id="il-chicago",
        name="Archdiocese of Chicago",
        state="IL",
        website="https://archchicago.org",
        parish_directory_url="https://directory.archchicago.org/parishes",
        parish_directory_kind="html_list",
    ),
    Diocese(
        id="ma-boston",
        name="Archdiocese of Boston",
        state="MA",
        website="https://bostoncatholic.org",
        parish_directory_url=None,
        parish_directory_kind="unknown",
        notes="Directory format not yet classified.",
    ),
    Diocese(
        id="ca-los-angeles",
        name="Archdiocese of Los Angeles",
        state="CA",
        website="https://lacatholics.org",
        parish_directory_url=None,
        parish_directory_kind="unknown",
    ),
]


def by_id(diocese_id: str) -> Diocese | None:
    for d in US_DIOCESES:
        if d.id == diocese_id:
            return d
    return None


def by_state(state: str) -> list[Diocese]:
    return [d for d in US_DIOCESES if d.state == state]


def with_directory() -> list[Diocese]:
    """Dioceses we can actually scrape today."""
    return [d for d in US_DIOCESES if d.parish_directory_kind != "unknown"]
