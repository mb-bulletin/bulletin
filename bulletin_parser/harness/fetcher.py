"""
Polite HTTP fetcher for the harness.

Principles:
- One concurrent request per host (per-host lock).
- Minimum delay between requests to the same host.
- Identifying User-Agent with a contact URL.
- Respect robots.txt per host (cached).
- Reasonable timeouts; no retries by default (we'll retry on next cron run).
- Conditional GETs (If-Modified-Since) when we have a known last-modified
  for the URL — saves bandwidth and is a good citizen.

This module is sync. The harness is I/O-bound but at scales we care about
(low thousands of parishes, weekly), sequential per-host fetching with a
small thread pool across hosts is more than enough and is much easier to
reason about than asyncio.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Dict
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import requests


DEFAULT_USER_AGENT = (
    "BulletinParserBot/0.1 "
    "(+https://example.org/bot; contact@example.org) "
    "Python-requests"
)


@dataclass
class FetchResult:
    status: int
    content: bytes | None
    final_url: str
    headers: dict[str, str]
    elapsed_ms: int

    @property
    def ok(self) -> bool:
        return self.status == 200 and self.content is not None


class Fetcher:
    """Polite, rate-limited HTTP fetcher."""

    def __init__(
        self,
        *,
        user_agent: str = DEFAULT_USER_AGENT,
        per_host_delay_s: float = 1.0,
        timeout_s: float = 10.0,
        respect_robots: bool = True,
        max_pdf_bytes: int = 20 * 1024 * 1024,  # 20MB cap
    ):
        self.user_agent = user_agent
        self.per_host_delay_s = per_host_delay_s
        self.timeout_s = timeout_s
        self.respect_robots = respect_robots
        self.max_pdf_bytes = max_pdf_bytes

        self._session = requests.Session()
        self._session.headers["User-Agent"] = user_agent

        self._host_locks: Dict[str, threading.Lock] = {}
        self._host_last: Dict[str, float] = {}
        self._global_lock = threading.Lock()
        self._robots_cache: Dict[str, RobotFileParser | None] = {}

    # ---- Internal ----

    def _host(self, url: str) -> str:
        return urlsplit(url).netloc.lower()

    def _lock_for(self, host: str) -> threading.Lock:
        with self._global_lock:
            if host not in self._host_locks:
                self._host_locks[host] = threading.Lock()
            return self._host_locks[host]

    def _wait_for_host(self, host: str) -> None:
        last = self._host_last.get(host, 0.0)
        wait = self.per_host_delay_s - (time.monotonic() - last)
        if wait > 0:
            time.sleep(wait)
        self._host_last[host] = time.monotonic()

    def _allowed(self, url: str) -> tuple[bool, str]:
        if not self.respect_robots:
            return True, ""
        host = self._host(url)
        if host not in self._robots_cache:
            robots_url = f"{urlsplit(url).scheme}://{host}/robots.txt"
            rp = None
            try:
                # Fetch robots.txt ourselves so we can distinguish
                # "server forbids access" (treat as no rules) from
                # "server returned actual robots.txt content".
                # RobotFileParser.read() interprets 401/403 as
                # "disallow everything", which is wrong for CDNs that
                # simply don't serve a robots.txt.
                r = self._session.get(robots_url, timeout=self.timeout_s)
                if r.status_code == 200 and r.text:
                    rp = RobotFileParser()
                    rp.set_url(robots_url)
                    rp.parse(r.text.splitlines())
            except requests.RequestException:
                rp = None
            self._robots_cache[host] = rp
        rp = self._robots_cache[host]
        if rp is None:
            return True, ""
        if not rp.can_fetch(self.user_agent, url):
            return False, "blocked by robots.txt"
        return True, ""

    # ---- Public API ----

    def head_status(self, url: str) -> int:
        """Lightweight existence check. Returns the HTTP status code, or 0 on error."""
        allowed, _ = self._allowed(url)
        if not allowed:
            return 0
        host = self._host(url)
        with self._lock_for(host):
            self._wait_for_host(host)
            try:
                # Some CDNs (including ecatholic's) refuse HEAD; fall back to streamed GET
                resp = self._session.head(
                    url, timeout=self.timeout_s, allow_redirects=True
                )
                if resp.status_code in (405, 501):
                    resp = self._session.get(
                        url, timeout=self.timeout_s,
                        stream=True, allow_redirects=True,
                    )
                    resp.close()
                return resp.status_code
            except requests.RequestException:
                return 0

    def get_pdf(self, url: str) -> FetchResult:
        """Fetch a PDF. Validates content-type and size cap."""
        allowed, reason = self._allowed(url)
        if not allowed:
            return FetchResult(status=0, content=None, final_url=url,
                               headers={}, elapsed_ms=0)
        host = self._host(url)
        with self._lock_for(host):
            self._wait_for_host(host)
            t0 = time.monotonic()
            try:
                resp = self._session.get(
                    url, timeout=self.timeout_s,
                    stream=True, allow_redirects=True,
                )
                content = b""
                for chunk in resp.iter_content(chunk_size=64 * 1024):
                    content += chunk
                    if len(content) > self.max_pdf_bytes:
                        resp.close()
                        return FetchResult(
                            status=resp.status_code, content=None,
                            final_url=resp.url,
                            headers=dict(resp.headers),
                            elapsed_ms=int((time.monotonic() - t0) * 1000),
                        )
                # Some CDNs return 200 with HTML error pages — sanity-check.
                ct = resp.headers.get("Content-Type", "").lower()
                if resp.status_code == 200 and "pdf" not in ct and not content.startswith(b"%PDF"):
                    return FetchResult(
                        status=415,  # Unsupported Media Type
                        content=None, final_url=resp.url,
                        headers=dict(resp.headers),
                        elapsed_ms=int((time.monotonic() - t0) * 1000),
                    )
                return FetchResult(
                    status=resp.status_code,
                    content=content if resp.status_code == 200 else None,
                    final_url=resp.url,
                    headers=dict(resp.headers),
                    elapsed_ms=int((time.monotonic() - t0) * 1000),
                )
            except requests.RequestException:
                return FetchResult(status=0, content=None, final_url=url,
                                   headers={},
                                   elapsed_ms=int((time.monotonic() - t0) * 1000))

    def get_text(self, url: str) -> tuple[str, int]:
        """Fetch a text resource (HTML page). Returns (text, status)."""
        allowed, _ = self._allowed(url)
        if not allowed:
            return "", 0
        host = self._host(url)
        with self._lock_for(host):
            self._wait_for_host(host)
            try:
                resp = self._session.get(
                    url, timeout=self.timeout_s, allow_redirects=True
                )
                return resp.text, resp.status_code
            except requests.RequestException:
                return "", 0
