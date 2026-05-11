"""
Discovery: given a parish record, return the URL of its current bulletin PDF.

Three strategies, dispatched by `parish.host_kind`:

1. **ecatholic**: the CDN serves bulletins at predictable URLs:
       https://files.ecatholic.com/{parish_id}/bulletins/{YYYYMMDD}.pdf?t={...}
   The `?t=` cache-buster is set by ecatholic when the bulletin is uploaded.
   We don't know it in advance, but the URL still resolves without it.
   We resolve the Sunday date for the current bulletin (parishes typically
   upload on Friday/Saturday for Sunday) and probe.

2. **generic_html**: scrape the parish's /bulletins page and find the most
   recent PDF link. This is brittle by design — the long tail of parishes
   need this — and we cap it with a small set of heuristics.

3. **manual_url**: the parish always serves their bulletin at a fixed URL
   that we just fetch directly. Useful for parishes whose CMS writes a
   "latest.pdf" symlink or similar.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable
from urllib.parse import urljoin


@dataclass
class DiscoveryResult:
    url: str | None
    note: str = ""    # explanation for the audit log


def latest_sunday(today: date | None = None) -> date:
    """The Sunday whose bulletin should be live today.

    Bulletins for Sunday N are typically uploaded Friday/Saturday before N
    and are 'current' through the following Friday. We treat the latest
    Sunday on-or-before today (or the upcoming Sunday from Friday onward)
    as the target.
    """
    today = today or date.today()
    weekday = today.weekday()  # Mon=0..Sun=6
    if weekday in (4, 5):
        # Fri/Sat: this Sunday's bulletin may already be up
        return today + timedelta(days=(6 - weekday))
    # Sun..Thu: the most recent Sunday
    return today - timedelta(days=(weekday + 1) % 7)


def candidate_ecatholic_urls(
    ecatholic_id: str, target: date, lookback_weeks: int = 4
) -> list[str]:
    """Generate candidate URLs to probe.

    We probe the target Sunday first, then walk back week by week. This
    handles the common case where a parish hasn't uploaded *this* week's
    bulletin yet but had one last week.
    """
    urls = []
    for i in range(lookback_weeks):
        d = target - timedelta(days=7 * i)
        urls.append(
            f"https://files.ecatholic.com/{ecatholic_id}/bulletins/"
            f"{d.strftime('%Y%m%d')}.pdf"
        )
    return urls


# Regex for "looks like a bulletin PDF" — broad enough for the messy
# real-world page markup we'll see.
_PDF_HREF_RE = re.compile(
    r"""href=["']([^"']+\.pdf(?:\?[^"']*)?)["']""",
    re.IGNORECASE,
)
_DATE_IN_NAME_RE = re.compile(r"(20\d{6})|(\d{4}[-_]\d{2}[-_]\d{2})")


def scrape_pdf_links(html: str, base_url: str) -> list[tuple[str, str | None]]:
    """Extract (absolute_url, embedded_date_or_None) pairs from a page."""
    out: list[tuple[str, str | None]] = []
    for m in _PDF_HREF_RE.finditer(html):
        href = m.group(1)
        url = urljoin(base_url, href)
        date_m = _DATE_IN_NAME_RE.search(href)
        out.append((url, date_m.group(0) if date_m else None))
    return out


def pick_latest_pdf(
    pdf_links: Iterable[tuple[str, str | None]]
) -> str | None:
    """From a list of PDF links on a /bulletins page, pick the most recent."""
    dated, undated = [], []
    for url, datestr in pdf_links:
        if datestr:
            # Normalize to YYYYMMDD for sorting
            digits = re.sub(r"\D", "", datestr)
            if len(digits) == 8:
                dated.append((digits, url))
        else:
            undated.append(url)
    if dated:
        dated.sort(reverse=True)
        return dated[0][1]
    # Fallback: page-order first PDF (typically newest at top)
    return undated[0] if undated else None


class Discovery:
    """Resolves a parish row -> current bulletin URL."""

    def __init__(self, fetcher):
        self.fetcher = fetcher

    def resolve(self, parish) -> DiscoveryResult:
        kind = parish["host_kind"]
        if kind == "manual_url":
            return DiscoveryResult(parish["manual_url"], note="manual URL")
        if kind == "ecatholic":
            return self._resolve_ecatholic(parish)
        if kind == "generic_html":
            return self._resolve_generic(parish)
        return DiscoveryResult(None, note=f"unknown host_kind: {kind}")

    def _resolve_ecatholic(self, parish) -> DiscoveryResult:
        eid = parish["ecatholic_id"]
        if not eid:
            return DiscoveryResult(None, note="ecatholic_id missing")
        target = latest_sunday()
        for url in candidate_ecatholic_urls(eid, target):
            status = self.fetcher.head_status(url)
            if status == 200:
                return DiscoveryResult(url, note=f"resolved at {url}")
        return DiscoveryResult(None, note=f"no bulletin found in 4-week window from {target}")

    def _resolve_generic(self, parish) -> DiscoveryResult:
        page = parish["bulletins_url"]
        if not page:
            return DiscoveryResult(None, note="bulletins_url missing")
        html, status = self.fetcher.get_text(page)
        if status != 200 or not html:
            return DiscoveryResult(None, note=f"bulletins page returned {status}")
        links = scrape_pdf_links(html, page)
        if not links:
            return DiscoveryResult(None, note="no PDF links on bulletins page")
        url = pick_latest_pdf(links)
        return DiscoveryResult(url, note=f"picked from {len(links)} PDF link(s) on page")
