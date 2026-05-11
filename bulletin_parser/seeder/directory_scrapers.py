"""
Per-diocese parish directory scrapers.

Each diocese publishes its parish list in a different format. The base
class defines the contract; concrete scrapers implement it per format.

What a scraper returns: a list of ScrapedParish records. The seeder
pipeline then runs each one through the HostDetector to figure out the
bulletin URL and produces final roster entries.

NB: the scrapers in this module operate on HTML strings, not URLs.
The orchestration (fetch the URL, pass HTML in) lives in the
seeder CLI/orchestrator so the scrapers themselves are pure and
testable with fixture files.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit


@dataclass(frozen=True)
class ScrapedParish:
    name: str
    homepage_url: str | None
    city: str | None = None
    state: str | None = None
    diocese_id: str | None = None       # filled in by the orchestrator
    raw_text: str = ""                   # the directory entry's source text, for debugging


class DirectoryScraper(ABC):
    """Subclass per diocese / per directory format."""

    @abstractmethod
    def scrape(self, html: str, base_url: str) -> list[ScrapedParish]:
        ...


# ---- HTML-list scrapers --------------------------------------------------

# Regex to find candidate parish entries in a typical HTML directory.
# This is intentionally loose — different sites mark up entries differently;
# we look for blocks that contain a parish-looking link plus address-looking
# text nearby. Specific scrapers below tighten this with site-specific selectors
# where it matters.
_PARISH_LINK_RE = re.compile(
    r"""<a\s[^>]*href=["']([^"']+)["'][^>]*>\s*([^<]{4,160})\s*</a>""",
    re.IGNORECASE,
)

# A list of words that strongly suggest a link is to a parish, not nav chrome.
_PARISH_NAME_HINTS = re.compile(
    r"\b(?:church|parish|cathedral|basilica|chapel|shrine|mission)\b"
    r"|^(?:st\.?|saint|our lady|holy|sacred|blessed|christ|mary)\b",
    re.IGNORECASE,
)

# Things that look like nav/chrome and should be excluded
_EXCLUDE_LINK_TEXT = re.compile(
    r"^(?:home|contact|search|login|register|donate|menu|skip to|next|previous|"
    r"all parishes|find a parish|view (?:all|map))$",
    re.IGNORECASE,
)


def _looks_like_parish_link(text: str) -> bool:
    text = text.strip()
    if not text or len(text) > 120:
        return False
    if _EXCLUDE_LINK_TEXT.match(text):
        return False
    return bool(_PARISH_NAME_HINTS.search(text))


def _absolutize(href: str, base_url: str) -> str | None:
    """Resolve a relative href against base_url. Returns None for bad URLs."""
    if not href or href.startswith("#") or href.startswith("javascript:"):
        return None
    if href.startswith("mailto:") or href.startswith("tel:"):
        return None
    return urljoin(base_url, href)


def _is_internal_link(url: str, base_url: str) -> bool:
    """True if `url` points to the same host as `base_url`."""
    return urlsplit(url).netloc == urlsplit(base_url).netloc


class GenericHtmlListScraper(DirectoryScraper):
    """A best-effort scraper for diocesan parish-list pages.

    Finds <a> tags whose text looks like a parish name and whose href
    appears to be a parish-detail page (internal link). This handles
    the common case of `<ul><li><a href="/parishes/st-jane">St. Jane</a></li>...`
    pages.

    Many diocesan sites link to the parish's *external* website directly
    from the directory; we accept both internal detail pages and external
    parish homepages. The orchestrator's host detector handles either.
    """

    def __init__(self, *, allow_external: bool = True):
        self.allow_external = allow_external

    def scrape(self, html: str, base_url: str) -> list[ScrapedParish]:
        seen_urls: set[str] = set()
        out: list[ScrapedParish] = []
        for href, text in _PARISH_LINK_RE.findall(html):
            text = _strip_tags(text).strip()
            if not _looks_like_parish_link(text):
                continue
            url = _absolutize(href, base_url)
            if not url:
                continue
            if not self.allow_external and not _is_internal_link(url, base_url):
                continue
            # Dedup: many directories link the same parish twice (name + photo)
            key = (url, text.lower())
            if key in seen_urls:
                continue
            seen_urls.add(key)
            out.append(ScrapedParish(name=text, homepage_url=url, raw_text=text))
        return out


def _strip_tags(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s)


# ---- Sitemap scraper ----------------------------------------------------

_SITEMAP_LOC_RE = re.compile(r"<loc>\s*(.*?)\s*</loc>", re.IGNORECASE)


class SitemapScraper(DirectoryScraper):
    """Some dioceses expose parish URLs via /sitemap.xml.

    This scraper extracts URLs matching a pattern (e.g. `/parishes/.*`)
    and treats each as a parish detail page.
    """

    def __init__(self, url_pattern: re.Pattern[str]):
        self.url_pattern = url_pattern

    def scrape(self, html: str, base_url: str) -> list[ScrapedParish]:
        # `html` here is the sitemap XML body.
        out: list[ScrapedParish] = []
        for loc in _SITEMAP_LOC_RE.findall(html):
            if not self.url_pattern.search(loc):
                continue
            # Try to extract a parish name from the URL slug as a placeholder.
            slug = loc.rstrip("/").rsplit("/", 1)[-1]
            name = slug.replace("-", " ").replace("_", " ").title()
            out.append(ScrapedParish(name=name, homepage_url=loc, raw_text=loc))
        return out


# ---- Scraper registry ---------------------------------------------------

def scraper_for(directory_kind: str) -> DirectoryScraper | None:
    """Resolve a diocese.parish_directory_kind to a scraper.

    Sitemap scrapers need a URL pattern — the seeder creates those
    inline since the pattern is diocese-specific.
    """
    if directory_kind == "html_list":
        return GenericHtmlListScraper()
    return None  # sitemap, json_api, manual, unknown — handled by caller
