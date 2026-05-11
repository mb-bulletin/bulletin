"""
Ingestion orchestrator.

For each active parish:
  1. Resolve the current bulletin URL (Discovery).
  2. Fetch the PDF (Fetcher).
  3. Hash the bytes; dedup against previously-fetched bulletins.
  4. If new, save the PDF, extract text, run the parser, save the parse.
  5. Log every step to fetch_attempts for observability.

Parallelism is across hosts, not within a host (the Fetcher enforces
per-host serialization with a delay).
"""

from __future__ import annotations

import hashlib
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..extract import extract_text_from_pdf
from ..parser import DEFAULT_MODEL, parse_bulletin
from ..schema import Bulletin
from .discovery import Discovery
from .fetcher import Fetcher
from .storage import Storage


log = logging.getLogger(__name__)


@dataclass
class IngestionStats:
    parishes_checked: int = 0
    new_bulletins: int = 0
    unchanged: int = 0
    discovery_failed: int = 0
    fetch_errors: int = 0
    parse_errors: int = 0


def _default_parse_fn(pdf_path: Path, model: str) -> Bulletin:
    """Default parse: extract text from the PDF then call the LLM parser."""
    text = extract_text_from_pdf(pdf_path)
    return parse_bulletin(text, model=model)


class Orchestrator:
    def __init__(
        self,
        storage: Storage,
        fetcher: Fetcher | None = None,
        *,
        max_workers: int = 4,
        skip_parse: bool = False,
        parse_fn: Callable[[Path], Bulletin] | None = None,
        model: str = DEFAULT_MODEL,
    ):
        self.storage = storage
        self.fetcher = fetcher or Fetcher()
        self.discovery = Discovery(self.fetcher)
        self.max_workers = max_workers
        self.skip_parse = skip_parse
        self.model = model
        # Injectable for tests so we don't need an API key or real PDFs
        self._parse = parse_fn or (lambda p: _default_parse_fn(p, model))

    # ---- Per-parish flow ----

    def process_parish(self, parish) -> str:
        """Run the full pipeline for one parish. Returns the outcome string."""
        pid = parish["id"]
        log.info("→ %s (%s)", pid, parish["name"])

        # 1. Discover
        disc = self.discovery.resolve(parish)
        if not disc.url:
            self.storage.log_attempt(
                pid, outcome="discovery_failed", error_message=disc.note
            )
            self.storage.mark_checked(pid)
            return "discovery_failed"

        # 2. Fetch
        result = self.fetcher.get_pdf(disc.url)
        if not result.ok:
            self.storage.log_attempt(
                pid, outcome="http_error" if result.status else "not_found",
                url=disc.url, http_status=result.status,
                bytes_fetched=len(result.content) if result.content else 0,
                error_message=f"HTTP {result.status}",
            )
            self.storage.mark_checked(pid)
            return "http_error"

        # 3. Dedup
        content_sha = hashlib.sha256(result.content).hexdigest()
        existing = self.storage.find_bulletin_by_hash(pid, content_sha)
        if existing:
            self.storage.log_attempt(
                pid, outcome="unchanged",
                url=disc.url, http_status=200,
                bytes_fetched=len(result.content),
                bulletin_id=existing["id"],
            )
            self.storage.mark_checked(pid)
            return "unchanged"

        # 4. Save the PDF
        bulletin_id, pdf_path = self.storage.save_bulletin(
            pid, content_sha, result.content, result.final_url
        )

        # 5. Parse (unless disabled)
        if self.skip_parse:
            self.storage.log_attempt(
                pid, outcome="new", url=disc.url, http_status=200,
                bytes_fetched=len(result.content), bulletin_id=bulletin_id,
            )
            self.storage.mark_checked(pid)
            return "new"

        try:
            bulletin = self._parse(pdf_path)
            self.storage.save_parse(
                bulletin_id,
                parser_version=bulletin.parser_version,
                model=self.model,
                payload=bulletin.model_dump(mode="json"),
            )
            self.storage.log_attempt(
                pid, outcome="new", url=disc.url, http_status=200,
                bytes_fetched=len(result.content), bulletin_id=bulletin_id,
            )
            self.storage.mark_checked(pid)
            return "new"
        except Exception as e:
            log.exception("parse failed for %s", pid)
            self.storage.save_parse(
                bulletin_id,
                parser_version="unknown",
                model=self.model,
                payload=None,
                parse_error=f"{type(e).__name__}: {e}",
            )
            self.storage.log_attempt(
                pid, outcome="parse_error", url=disc.url, http_status=200,
                bytes_fetched=len(result.content), bulletin_id=bulletin_id,
                error_message=f"{type(e).__name__}: {e}",
            )
            self.storage.mark_checked(pid)
            return "parse_error"

    # ---- Batch ----

    def run_once(self) -> IngestionStats:
        parishes = self.storage.list_active_parishes()
        stats = IngestionStats(parishes_checked=len(parishes))

        with ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            futures = {ex.submit(self.process_parish, p): p["id"] for p in parishes}
            for f in as_completed(futures):
                outcome = f.result()
                if outcome == "new":
                    stats.new_bulletins += 1
                elif outcome == "unchanged":
                    stats.unchanged += 1
                elif outcome == "discovery_failed":
                    stats.discovery_failed += 1
                elif outcome == "http_error":
                    stats.fetch_errors += 1
                elif outcome == "parse_error":
                    stats.parse_errors += 1

        return stats
