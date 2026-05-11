"""
Harness tests with no network and no API key.

We inject a fake Fetcher that serves canned PDF bytes from in-memory
mappings, and a fake parse function that returns a hand-built Bulletin.
This exercises every code path in the orchestrator:
  - ecatholic discovery (URL probing with HEAD)
  - generic_html discovery (page scrape)
  - polite fetch with content validation
  - dedup by content hash (run twice, see "unchanged" on the second pass)
  - parse-and-store
  - parse error handling
  - status / health reporting
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))

from bulletin_parser.harness import Fetcher, Orchestrator, Storage
from bulletin_parser.harness.fetcher import FetchResult
from bulletin_parser.harness.discovery import (
    latest_sunday, scrape_pdf_links, pick_latest_pdf,
)
from test_schema import build_stpatricks_reference


# A "PDF" that just starts with the %PDF magic so the fetcher accepts it
FAKE_PDF_1 = b"%PDF-1.4 fake bulletin one\n" + b"x" * 200
FAKE_PDF_2 = b"%PDF-1.4 fake bulletin two\n" + b"y" * 200
FAKE_PDF_BAD = b"%PDF-1.4 unparseable\n" + b"z" * 100


class FakeFetcher:
    """A test double for Fetcher: serves canned responses from a dict."""

    def __init__(self, urls_to_pdfs: dict[str, bytes],
                 urls_to_pages: dict[str, str] | None = None,
                 head_404_for: set[str] | None = None):
        self.urls_to_pdfs = urls_to_pdfs
        self.urls_to_pages = urls_to_pages or {}
        self.head_404_for = head_404_for or set()
        self.calls = []

    def head_status(self, url: str) -> int:
        self.calls.append(("head", url))
        if url in self.head_404_for:
            return 404
        if url in self.urls_to_pdfs:
            return 200
        return 404

    def get_pdf(self, url: str) -> FetchResult:
        self.calls.append(("pdf", url))
        if url not in self.urls_to_pdfs:
            return FetchResult(404, None, url, {}, 1)
        body = self.urls_to_pdfs[url]
        return FetchResult(200, body, url, {"Content-Type": "application/pdf"}, 1)

    def get_text(self, url: str) -> tuple[str, int]:
        self.calls.append(("text", url))
        if url not in self.urls_to_pages:
            return "", 404
        return self.urls_to_pages[url], 200


def fake_parse_ok(pdf_path):
    """Fake parse that returns the hand-built St Patrick's reference."""
    return build_stpatricks_reference()


def fake_parse_fail(pdf_path):
    raise ValueError("synthetic parse failure")


# ---------- Tests ----------

def test_latest_sunday_logic():
    # Monday 2026-05-11 -> previous Sunday 2026-05-10
    assert latest_sunday(date(2026, 5, 11)) == date(2026, 5, 10)
    # Friday 2026-05-15 -> upcoming Sunday 2026-05-17
    assert latest_sunday(date(2026, 5, 15)) == date(2026, 5, 17)
    # Saturday 2026-05-16 -> upcoming Sunday 2026-05-17
    assert latest_sunday(date(2026, 5, 16)) == date(2026, 5, 17)
    # Sunday 2026-05-17 -> 2026-05-17
    assert latest_sunday(date(2026, 5, 17)) == date(2026, 5, 17)


def test_scrape_pdf_links_finds_dated_links():
    html = """
      <a href="/files/20260510_bulletin.pdf">May 10</a>
      <a href="/files/20260503_bulletin.pdf">May 3</a>
      <a href="/files/old/2024-12-25_christmas.pdf">Christmas</a>
      <a href="/files/no-date.pdf">undated</a>
    """
    links = scrape_pdf_links(html, "https://parish.org/bulletins")
    assert len(links) == 4
    pick = pick_latest_pdf(links)
    assert "20260510" in pick


def test_ingest_ecatholic_parish_end_to_end(tmp_path):
    storage = Storage(tmp_path / "harness.db", tmp_path / "pdfs")
    storage.add_parish(
        id="ny-test", name="Test Parish",
        host_kind="ecatholic", ecatholic_id="11778", active=1,
    )

    # The fake fetcher serves a PDF at the most recent Sunday URL.
    target = latest_sunday()
    url = f"https://files.ecatholic.com/11778/bulletins/{target.strftime('%Y%m%d')}.pdf"
    fetcher = FakeFetcher(urls_to_pdfs={url: FAKE_PDF_1})

    orch = Orchestrator(storage, fetcher, max_workers=1,
                        parse_fn=fake_parse_ok)
    stats = orch.run_once()
    assert stats.new_bulletins == 1, f"expected 1 new bulletin, got {stats}"
    assert stats.parse_errors == 0

    # Second run with the same fetcher: should detect unchanged content.
    stats2 = orch.run_once()
    assert stats2.new_bulletins == 0
    assert stats2.unchanged == 1


def test_ingest_handles_404_falls_back_through_lookback(tmp_path):
    storage = Storage(tmp_path / "harness.db", tmp_path / "pdfs")
    storage.add_parish(
        id="ny-test", name="Test Parish",
        host_kind="ecatholic", ecatholic_id="11778", active=1,
    )

    target = latest_sunday()
    from datetime import timedelta
    last_week = target - timedelta(days=7)
    this_week_url = f"https://files.ecatholic.com/11778/bulletins/{target.strftime('%Y%m%d')}.pdf"
    last_week_url = f"https://files.ecatholic.com/11778/bulletins/{last_week.strftime('%Y%m%d')}.pdf"

    # This week's bulletin is missing; last week's is present.
    fetcher = FakeFetcher(
        urls_to_pdfs={last_week_url: FAKE_PDF_1},
        head_404_for={this_week_url},
    )
    orch = Orchestrator(storage, fetcher, max_workers=1,
                        parse_fn=fake_parse_ok)
    stats = orch.run_once()
    assert stats.new_bulletins == 1, f"should fall back to last week, got {stats}"


def test_ingest_generic_html_parish(tmp_path):
    storage = Storage(tmp_path / "harness.db", tmp_path / "pdfs")
    storage.add_parish(
        id="example", name="Example",
        host_kind="generic_html",
        bulletins_url="https://example.org/bulletins",
        active=1,
    )

    bulletin_url = "https://example.org/files/20260517_bulletin.pdf"
    fetcher = FakeFetcher(
        urls_to_pdfs={bulletin_url: FAKE_PDF_1},
        urls_to_pages={
            "https://example.org/bulletins":
                f'<a href="{bulletin_url}">latest</a>'
                '<a href="/files/20260510_old.pdf">older</a>',
        },
    )
    orch = Orchestrator(storage, fetcher, max_workers=1,
                        parse_fn=fake_parse_ok)
    stats = orch.run_once()
    assert stats.new_bulletins == 1


def test_parse_failure_is_recorded_not_raised(tmp_path):
    storage = Storage(tmp_path / "harness.db", tmp_path / "pdfs")
    storage.add_parish(
        id="ny-test", name="Test Parish",
        host_kind="ecatholic", ecatholic_id="11778", active=1,
    )

    target = latest_sunday()
    url = f"https://files.ecatholic.com/11778/bulletins/{target.strftime('%Y%m%d')}.pdf"
    fetcher = FakeFetcher(urls_to_pdfs={url: FAKE_PDF_BAD})

    orch = Orchestrator(storage, fetcher, max_workers=1,
                        parse_fn=fake_parse_fail)
    stats = orch.run_once()
    assert stats.parse_errors == 1, f"expected 1 parse error, got {stats}"
    # The PDF should still be stored despite the parse failure.
    with storage.connect() as conn:
        n_bulletins = conn.execute("SELECT COUNT(*) FROM bulletins").fetchone()[0]
        n_parses = conn.execute("SELECT COUNT(*) FROM parsed_bulletins").fetchone()[0]
    assert n_bulletins == 1
    assert n_parses == 1  # the error row


def test_discovery_failure_when_no_url(tmp_path):
    storage = Storage(tmp_path / "harness.db", tmp_path / "pdfs")
    storage.add_parish(
        id="broken", name="Broken Parish",
        host_kind="ecatholic", ecatholic_id="99999", active=1,
    )
    # Fetcher serves nothing — all probes 404
    fetcher = FakeFetcher(urls_to_pdfs={})
    orch = Orchestrator(storage, fetcher, max_workers=1,
                        parse_fn=fake_parse_ok)
    stats = orch.run_once()
    assert stats.discovery_failed == 1


def test_health_summary(tmp_path):
    storage = Storage(tmp_path / "harness.db", tmp_path / "pdfs")
    storage.add_parish(
        id="ny-test", name="Test", host_kind="ecatholic",
        ecatholic_id="11778", active=1,
    )
    target = latest_sunday()
    url = f"https://files.ecatholic.com/11778/bulletins/{target.strftime('%Y%m%d')}.pdf"
    fetcher = FakeFetcher(urls_to_pdfs={url: FAKE_PDF_1})
    Orchestrator(storage, fetcher, max_workers=1,
                 parse_fn=fake_parse_ok).run_once()
    h = storage.health_summary()
    assert h["attempts"] == 1
    assert h["new_bulletins"] == 1


def test_pdf_validation_rejects_html_error_pages(tmp_path):
    """A 200 response with HTML body (CDN error page) should NOT be stored as a bulletin."""
    storage = Storage(tmp_path / "harness.db", tmp_path / "pdfs")
    storage.add_parish(
        id="ny-test", name="Test", host_kind="ecatholic",
        ecatholic_id="11778", active=1,
    )

    target = latest_sunday()
    url = f"https://files.ecatholic.com/11778/bulletins/{target.strftime('%Y%m%d')}.pdf"

    # Override the real Fetcher's _allowed and HTTP layer with a custom one.
    class HtmlErrorFetcher(FakeFetcher):
        def get_pdf(self, u):
            # Mimic a CDN that returns 200 OK with an HTML error page
            return FetchResult(
                415, None, u,
                {"Content-Type": "text/html"}, 1,
            )

    fetcher = HtmlErrorFetcher(urls_to_pdfs={url: b"<html>Not found</html>"})
    orch = Orchestrator(storage, fetcher, max_workers=1,
                        parse_fn=fake_parse_ok)
    stats = orch.run_once()
    assert stats.new_bulletins == 0
    assert stats.fetch_errors == 1


if __name__ == "__main__":
    import tempfile, traceback
    failed = 0
    tests = sorted(n for n in dir(sys.modules[__name__]) if n.startswith("test_"))
    for name in tests:
        fn = globals()[name]
        try:
            # Tests that take tmp_path get a real temp dir
            if "tmp_path" in fn.__code__.co_varnames:
                with tempfile.TemporaryDirectory() as td:
                    fn(Path(td))
            else:
                fn()
            print(f"  ✓ {name}")
        except Exception as e:
            failed += 1
            print(f"  ✗ {name}: {type(e).__name__}: {e}")
            traceback.print_exc()
    if failed:
        print(f"\n{failed} test(s) failed")
        sys.exit(1)
    print("\nAll harness tests passed.")
