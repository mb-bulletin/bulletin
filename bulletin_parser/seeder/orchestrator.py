"""
Seeder orchestrator: produces roster entries from diocesan directories.

Pipeline, per diocese:
  1. Fetch the parish directory page.
  2. Run the appropriate DirectoryScraper to get ScrapedParish records.
  3. For each parish, run the HostDetector to figure out host_kind /
     ecatholic_id / bulletins_url.
  4. Emit roster entries.

Output is a list of dict records ready to feed into the harness's
`add_parish` (or to be serialized to roster.json and loaded with
`harness init --roster`).

Failures are recorded, not raised — a diocese with a flaky directory
shouldn't break a seeding run for other dioceses. Each output record
includes `_provenance` with the diocese, scraper, and detector info so
the operator can audit results.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from ..harness.fetcher import Fetcher
from .directory_scrapers import (
    DirectoryScraper,
    GenericHtmlListScraper,
    ScrapedParish,
    SitemapScraper,
    scraper_for,
)
from .dioceses import Diocese
from .host_detector import DetectionResult, HostDetector


log = logging.getLogger(__name__)


@dataclass
class SeedingReport:
    """Summary of one seeding run, per-diocese."""
    diocese_id: str
    scraped: int = 0
    detected_ecatholic: int = 0
    detected_generic_html: int = 0
    detected_other: int = 0
    detected_unknown: int = 0
    errors: list[str] = field(default_factory=list)


def _slugify(s: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9\s-]", "", s).strip().lower()
    s = re.sub(r"\s+", "-", s)
    return s[:64]


def _make_parish_id(diocese_id: str, parish_name: str) -> str:
    return f"{diocese_id}--{_slugify(parish_name)}"


class Seeder:
    """Drives the diocese → roster-entries pipeline."""

    def __init__(self, fetcher: Fetcher | None = None,
                 *, detector: HostDetector | None = None):
        self.fetcher = fetcher or Fetcher()
        self.detector = detector or HostDetector(self.fetcher)

    # ---- Scraping a single diocese ----

    def scrape_diocese(self, diocese: Diocese) -> tuple[list[ScrapedParish], SeedingReport]:
        """Return the ScrapedParish list for a diocese plus a report."""
        report = SeedingReport(diocese_id=diocese.id)

        if diocese.parish_directory_url is None:
            report.errors.append("no parish_directory_url configured")
            return [], report
        scraper = self._scraper_for_diocese(diocese)
        if scraper is None:
            report.errors.append(
                f"no scraper for directory_kind={diocese.parish_directory_kind!r}"
            )
            return [], report

        html, status = self.fetcher.get_text(diocese.parish_directory_url)
        if status != 200 or not html:
            report.errors.append(
                f"GET {diocese.parish_directory_url} → {status}"
            )
            return [], report

        scraped = scraper.scrape(html, diocese.parish_directory_url)
        # Fill in diocese provenance on each ScrapedParish
        scraped = [
            ScrapedParish(
                name=p.name, homepage_url=p.homepage_url,
                city=p.city, state=p.state or diocese.state,
                diocese_id=diocese.id, raw_text=p.raw_text,
            )
            for p in scraped
        ]
        report.scraped = len(scraped)
        return scraped, report

    def _scraper_for_diocese(self, diocese: Diocese) -> DirectoryScraper | None:
        kind = diocese.parish_directory_kind
        if kind == "html_list":
            return GenericHtmlListScraper()
        if kind == "sitemap":
            # Caller would inject a configured SitemapScraper; for the
            # built-in dispatch we default to "anything under /parish".
            return SitemapScraper(url_pattern=re.compile(r"/parish", re.IGNORECASE))
        return None

    # ---- Detect host + build a roster entry ----

    def build_roster_entry(
        self, parish: ScrapedParish, diocese: Diocese
    ) -> tuple[dict[str, Any], DetectionResult]:
        """Run the detector against a scraped parish and produce a roster dict.

        The returned dict is ready to pass to `Storage.add_parish(**entry)`.
        """
        if parish.homepage_url is None:
            entry = self._base_entry(parish, diocese)
            entry["host_kind"] = "unknown"
            entry["notes"] = "scraped without a homepage URL"
            return entry, DetectionResult("unknown", evidence="no homepage URL")

        detection = self.detector.detect(parish.homepage_url)
        entry = self._base_entry(parish, diocese)
        entry["host_kind"] = detection.host_kind
        if detection.host_kind == "ecatholic":
            entry["ecatholic_id"] = detection.ecatholic_id
        elif detection.host_kind == "generic_html":
            entry["bulletins_url"] = detection.bulletins_url or parish.homepage_url
        elif detection.host_kind == "manual_url":
            entry["manual_url"] = detection.manual_url
        if detection.evidence:
            existing_notes = entry.get("notes") or ""
            entry["notes"] = (
                f"{existing_notes} [detector: {detection.evidence}]"
            ).strip()
        return entry, detection

    def _base_entry(self, parish: ScrapedParish, diocese: Diocese) -> dict[str, Any]:
        return {
            "id": _make_parish_id(diocese.id, parish.name),
            "name": parish.name,
            "diocese": diocese.name,
            "city": parish.city,
            "state": parish.state or diocese.state,
            "country": "US",
            "active": 1,
        }

    # ---- Run end-to-end for a diocese ----

    def seed_diocese(self, diocese: Diocese) -> tuple[list[dict[str, Any]], SeedingReport]:
        """Scrape + detect for one diocese. Returns (roster_entries, report)."""
        scraped, report = self.scrape_diocese(diocese)
        entries: list[dict[str, Any]] = []
        for p in scraped:
            try:
                entry, detection = self.build_roster_entry(p, diocese)
                entries.append(entry)
                if detection.host_kind == "ecatholic":
                    report.detected_ecatholic += 1
                elif detection.host_kind == "generic_html":
                    report.detected_generic_html += 1
                elif detection.host_kind == "unknown":
                    report.detected_unknown += 1
                else:
                    report.detected_other += 1
            except Exception as e:
                log.exception("build_roster_entry failed for %s", p.name)
                report.errors.append(f"{p.name}: {type(e).__name__}: {e}")
        return entries, report
