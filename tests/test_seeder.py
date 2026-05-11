"""
Tests for the seeder.

Covers:
  - directory_scrapers: parsing a synthesized diocesan parish list
  - host_detector: identifying ecatholic / generic / unknown from HTML
  - orchestrator: end-to-end with a fake fetcher serving local fixture HTML
  - CLI: list-dioceses runs cleanly
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bulletin_parser.seeder.dioceses import Diocese, by_id, with_directory
from bulletin_parser.seeder.directory_scrapers import (
    GenericHtmlListScraper,
    SitemapScraper,
)
from bulletin_parser.seeder.host_detector import (
    HostDetector,
    candidate_bulletin_urls,
    detect_from_html,
)
from bulletin_parser.seeder.orchestrator import Seeder, _slugify


FIXTURES = Path(__file__).resolve().parent / "seeder_fixtures"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text()


# ---------- Fake fetcher ----------

class FakeTextFetcher:
    """Serves canned HTML by URL, like the harness tests' fake fetcher
    but text-only (the seeder doesn't fetch PDFs)."""

    def __init__(self, urls_to_html: dict[str, str]):
        self.urls_to_html = urls_to_html
        self.requested: list[str] = []

    def get_text(self, url: str) -> tuple[str, int]:
        self.requested.append(url)
        if url in self.urls_to_html:
            return self.urls_to_html[url], 200
        return "", 404


# ---------- directory_scrapers ----------

def test_generic_html_list_scraper_finds_parishes():
    html = _read("diocese_directory.html")
    scraper = GenericHtmlListScraper()
    parishes = scraper.scrape(html, "https://example-archdiocese.org/parishes/")
    names = [p.name for p in parishes]
    # Should find every parish-looking link
    assert "St. John the Evangelist Parish" in names
    assert "Saint Mary Catholic Church" in names
    assert "Holy Family Parish" in names
    assert "The Basilica of St. Patrick's Old Cathedral" in names
    assert "Our Lady of Grace" in names
    assert "Sacred Heart Chapel" in names


def test_generic_html_list_scraper_dedupes():
    """The fixture has St John's linked twice (image + name)."""
    html = _read("diocese_directory.html")
    scraper = GenericHtmlListScraper()
    parishes = scraper.scrape(html, "https://example-archdiocese.org/parishes/")
    st_johns = [p for p in parishes if "John" in p.name]
    assert len(st_johns) == 1


def test_generic_html_list_scraper_excludes_chrome():
    html = _read("diocese_directory.html")
    scraper = GenericHtmlListScraper()
    parishes = scraper.scrape(html, "https://example-archdiocese.org/parishes/")
    names = [p.name for p in parishes]
    # Nav and chrome links should not appear
    for bad in ["Home", "Contact", "Donate", "Sitemap", "View all on a map",
                "About the Archdiocese"]:
        assert bad not in names, f"chrome link {bad!r} leaked into parish list"


def test_generic_html_list_scraper_absolutizes_relative_links():
    html = _read("diocese_directory.html")
    scraper = GenericHtmlListScraper()
    parishes = scraper.scrape(html, "https://example-archdiocese.org/parishes/")
    holy_family = next(p for p in parishes if "Holy Family" in p.name)
    assert holy_family.homepage_url == "https://example-archdiocese.org/parishes/holy-family"


def test_sitemap_scraper_filters_by_pattern():
    xml = """<?xml version="1.0"?>
    <urlset>
      <url><loc>https://example.org/</loc></url>
      <url><loc>https://example.org/about</loc></url>
      <url><loc>https://example.org/parishes/st-jane</loc></url>
      <url><loc>https://example.org/parishes/holy-cross</loc></url>
      <url><loc>https://example.org/news/article-1</loc></url>
    </urlset>"""
    scraper = SitemapScraper(url_pattern=re.compile(r"/parishes/"))
    parishes = scraper.scrape(xml, "https://example.org/sitemap.xml")
    assert len(parishes) == 2
    assert {"St Jane", "Holy Cross"} == {p.name for p in parishes}


# ---------- host_detector ----------

def test_detect_ecatholic_from_cdn_reference():
    html = _read("parish_ecatholic.html")
    result = detect_from_html(html, "https://oldcathedral.example.org")
    assert result.host_kind == "ecatholic"
    assert result.ecatholic_id == "11778"
    assert result.confidence > 0.9


def test_detect_generic_html_via_pdf_links():
    html = _read("parish_generic.html")
    result = detect_from_html(html, "https://stmary.example.org/bulletins")
    assert result.host_kind == "generic_html"
    assert result.bulletins_url == "https://stmary.example.org/bulletins"


def test_detect_unknown_when_no_signal():
    html = _read("parish_unknown.html")
    result = detect_from_html(html, "https://holyfamily.example.org")
    assert result.host_kind == "unknown"


def test_candidate_bulletin_urls_includes_common_paths():
    urls = candidate_bulletin_urls("https://example.org/")
    assert "https://example.org/bulletins" in urls
    assert "https://example.org/weekly-bulletin" in urls


def test_host_detector_falls_through_to_bulletins_page():
    """When the homepage has no fingerprint, the detector probes
    /bulletins and similar paths."""
    fetcher = FakeTextFetcher({
        "https://stmary.example.org/": _read("parish_unknown.html"),
        "https://stmary.example.org/bulletins": _read("parish_generic.html"),
    })
    detector = HostDetector(fetcher)
    result = detector.detect("https://stmary.example.org/")
    assert result.host_kind == "generic_html"
    assert result.bulletins_url == "https://stmary.example.org/bulletins"


# ---------- orchestrator end-to-end ----------

def test_seeder_end_to_end_for_a_diocese():
    """Scrape a diocesan directory, detect each parish's host, build entries."""
    diocese = Diocese(
        id="ex-test",
        name="Example Archdiocese",
        state="NY",
        website="https://example-archdiocese.org",
        parish_directory_url="https://example-archdiocese.org/parishes/",
        parish_directory_kind="html_list",
    )

    # Provide canned responses for the directory and a couple of parish sites
    fetcher = FakeTextFetcher({
        "https://example-archdiocese.org/parishes/": _read("diocese_directory.html"),
        "https://stjohnsexample.org": _read("parish_ecatholic.html"),
        "https://oldcathedral.example.org": _read("parish_ecatholic.html"),
        # Generic-html parish — homepage has no fingerprint, /bulletins does
        "https://www.stmarycatholic.example.org/": _read("parish_unknown.html"),
        "https://www.stmarycatholic.example.org/bulletins":
            _read("parish_generic.html"),
        # Holy Family: no fingerprint anywhere
        "https://example-archdiocese.org/parishes/holy-family":
            _read("parish_unknown.html"),
        "https://example-archdiocese.org/parishes/our-lady-of-grace":
            _read("parish_unknown.html"),
        "https://sacredheartchapel.example.org":
            _read("parish_unknown.html"),
    })

    seeder = Seeder(fetcher=fetcher)
    entries, report = seeder.seed_diocese(diocese)

    assert report.scraped == 6, f"expected 6 unique parishes, got {report.scraped}"
    # At least the two ecatholic-built parishes
    assert report.detected_ecatholic >= 2
    # At least one generic_html via fall-through
    assert report.detected_generic_html >= 1

    # Roster entries should have proper ids
    ids = [e["id"] for e in entries]
    assert all(id_.startswith("ex-test--") for id_ in ids)
    # Roster fields conform to what Storage.add_parish expects
    for entry in entries:
        assert "id" in entry and "name" in entry and "host_kind" in entry
        assert entry["state"] == "NY"
        assert entry["country"] == "US"

    # The ecatholic entries should have ecatholic_id set
    ecatholic_entries = [e for e in entries if e["host_kind"] == "ecatholic"]
    assert all(e.get("ecatholic_id") == "11778" for e in ecatholic_entries)


def test_seeder_records_error_when_directory_unreachable():
    diocese = Diocese(
        id="ex-broken",
        name="Broken Diocese",
        state="XX",
        website="https://broken.example.org",
        parish_directory_url="https://broken.example.org/parishes/",
        parish_directory_kind="html_list",
    )
    fetcher = FakeTextFetcher({})  # no canned responses → 404 everything
    seeder = Seeder(fetcher=fetcher)
    entries, report = seeder.seed_diocese(diocese)
    assert entries == []
    assert any("→ 404" in e for e in report.errors)


def test_seeder_handles_unknown_directory_kind():
    diocese = Diocese(
        id="ex-unclassified",
        name="Unclassified Diocese",
        state="XX",
        website="https://example.org",
        parish_directory_url=None,
        parish_directory_kind="unknown",
    )
    seeder = Seeder(fetcher=FakeTextFetcher({}))
    entries, report = seeder.seed_diocese(diocese)
    assert entries == []
    assert any("no parish_directory_url" in e for e in report.errors)


# ---------- dioceses + slugify ----------

def test_slugify():
    assert _slugify("St. John the Evangelist") == "st-john-the-evangelist"
    assert _slugify("Our Lady of Mt. Carmel") == "our-lady-of-mt-carmel"
    assert _slugify("The Basilica of St. Patrick's Old Cathedral") == \
        "the-basilica-of-st-patricks-old-cathedral"


def test_dioceses_seed_list_has_required_fields():
    assert any(d.parish_directory_kind != "unknown" for d in with_directory())
    ny = by_id("ny-new-york")
    assert ny is not None
    assert ny.parish_directory_url == "https://archny.org/parishes/"


# ---------- CLI smoke ----------

def test_list_dioceses_cli_runs(capsys=None):
    import io
    import contextlib
    from bulletin_parser.seeder.__main__ import main

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main(["list-dioceses"])
    out = buf.getvalue()
    assert rc == 0
    assert "Archdiocese of New York" in out
    assert "scrapeable" in out


if __name__ == "__main__":
    import traceback
    failed = 0
    tests = sorted(n for n in dir(sys.modules[__name__]) if n.startswith("test_"))
    for name in tests:
        fn = globals()[name]
        try:
            fn()
            print(f"  ✓ {name}")
        except Exception as e:
            failed += 1
            print(f"  ✗ {name}: {type(e).__name__}: {e}")
            traceback.print_exc()
    if failed:
        print(f"\n{failed} test(s) failed")
        sys.exit(1)
    print("\nAll seeder tests passed.")
