"""
Host detection for parish websites.

Given a parish's homepage URL (or its `/bulletins` page), figure out:
  - what `host_kind` to use in the harness roster
  - the `ecatholic_id` (if applicable)
  - the `bulletins_url` (if `host_kind=generic_html`)

This is the bridge between "we know this parish exists" and "the harness
can fetch its bulletin every week." The detector is heuristic: it
inspects HTML for known platform fingerprints and probes likely paths.

Order of checks:
  1. ecatholic — look for `files.ecatholic.com/{id}/` references in HTML,
     or any link to the ecatholic CDN.
  2. LPi (parishesonline.com / discoverparishlife.com) — fingerprint
     "Parishes Online" in the markup.
  3. Discover Mass — links to discovermass.com.
  4. Generic — find a `/bulletins` or `/weekly-bulletin` page that exists
     and contains PDF links.

If nothing matches, the parish is recorded with `host_kind=unknown` so a
human can investigate later.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urljoin, urlsplit


HostKind = Literal[
    "ecatholic",
    "generic_html",
    "lpi",            # Liturgical Publications Inc / parishesonline
    "discover_mass",
    "manual_url",
    "unknown",
]


@dataclass
class DetectionResult:
    host_kind: HostKind
    ecatholic_id: str | None = None
    bulletins_url: str | None = None
    manual_url: str | None = None
    confidence: float = 0.0  # 0.0 = guess; 1.0 = certain
    evidence: str = ""        # short explanation


# Common candidate paths for "where is the bulletins page on this parish site"
_BULLETIN_PATH_CANDIDATES = [
    "/bulletins",
    "/bulletin",
    "/weekly-bulletin",
    "/parish-bulletin",
    "/news/bulletins",
    "/our-parish/bulletins",
]

_ECATHOLIC_HOST_RE = re.compile(
    r"files\.ecatholic\.com/(\d+)/", re.IGNORECASE
)
_ECATHOLIC_BUILT_BY_RE = re.compile(
    r"(?:powered|built|made)\s+by\s+ecatholic", re.IGNORECASE
)
_LPI_FINGERPRINT_RE = re.compile(
    r"parishesonline\.com|discoverparishlife\.com|"
    r"liturgical[\s-]?publications", re.IGNORECASE
)
_DISCOVER_MASS_RE = re.compile(
    r"discovermass\.com", re.IGNORECASE
)
_PDF_LINK_RE = re.compile(
    r"""href=["']([^"']+\.pdf(?:\?[^"']*)?)["']""", re.IGNORECASE
)


def detect_from_html(html: str, source_url: str) -> DetectionResult:
    """Detect the host platform from a single page's HTML.

    `source_url` is the URL the HTML came from — used to resolve relative
    links and to set `bulletins_url` if we can't find anything more
    specific.
    """
    # 1. ecatholic — look for the CDN reference. If we find files.ecatholic.com/<id>/
    #    the parish_id is unambiguous from the URL itself.
    m = _ECATHOLIC_HOST_RE.search(html)
    if m:
        return DetectionResult(
            host_kind="ecatholic",
            ecatholic_id=m.group(1),
            confidence=0.95,
            evidence=f"files.ecatholic.com/{m.group(1)}/ referenced in page HTML",
        )
    if _ECATHOLIC_BUILT_BY_RE.search(html):
        # Built by ecatholic but no CDN reference on this page — we know
        # the host_kind but not the parish_id. Caller can probe further.
        return DetectionResult(
            host_kind="ecatholic",
            confidence=0.6,
            evidence="'powered by ecatholic' attribution found",
        )

    # 2. LPi / Parishes Online
    if _LPI_FINGERPRINT_RE.search(html):
        return DetectionResult(
            host_kind="lpi",
            confidence=0.8,
            evidence="parishesonline.com / LPi fingerprint matched",
        )

    # 3. Discover Mass
    if _DISCOVER_MASS_RE.search(html):
        return DetectionResult(
            host_kind="discover_mass",
            confidence=0.8,
            evidence="discovermass.com fingerprint matched",
        )

    # 4. Generic — does this page itself contain PDF links?
    pdf_links = _PDF_LINK_RE.findall(html)
    if pdf_links:
        return DetectionResult(
            host_kind="generic_html",
            bulletins_url=source_url,
            confidence=0.5,
            evidence=f"page contains {len(pdf_links)} PDF link(s)",
        )

    return DetectionResult(
        host_kind="unknown",
        confidence=0.0,
        evidence="no platform fingerprint matched",
    )


def candidate_bulletin_urls(homepage_url: str) -> list[str]:
    """Common paths where a parish's /bulletins page might live."""
    base = homepage_url.rstrip("/")
    return [base + p for p in _BULLETIN_PATH_CANDIDATES]


class HostDetector:
    """Stateful detector that uses a Fetcher to probe candidate pages.

    Two-stage:
      1. Inspect the homepage — covers ecatholic/LPi-built sites where the
         platform fingerprint is on every page.
      2. If still unknown, probe /bulletins and its variants — covers
         parishes hosted on Wix/Squarespace/WordPress that simply post
         PDFs on a bulletins page.
    """

    def __init__(self, fetcher):
        self.fetcher = fetcher

    def detect(self, homepage_url: str) -> DetectionResult:
        html, status = self.fetcher.get_text(homepage_url)
        if status == 200 and html:
            result = detect_from_html(html, homepage_url)
            if result.host_kind != "unknown":
                return result

        # Stage 2: probe likely bulletin pages
        for candidate in candidate_bulletin_urls(homepage_url):
            html, status = self.fetcher.get_text(candidate)
            if status != 200 or not html:
                continue
            result = detect_from_html(html, candidate)
            if result.host_kind != "unknown":
                return result
            # Even if no fingerprint, if the candidate URL exists and has
            # PDF links, that's a usable generic_html parish.
            pdf_links = _PDF_LINK_RE.findall(html)
            if pdf_links:
                return DetectionResult(
                    host_kind="generic_html",
                    bulletins_url=candidate,
                    confidence=0.5,
                    evidence=f"/bulletins-style page at {candidate} has {len(pdf_links)} PDFs",
                )

        return DetectionResult(
            host_kind="unknown",
            confidence=0.0,
            evidence=f"no fingerprint at {homepage_url} or candidate bulletin pages",
        )
