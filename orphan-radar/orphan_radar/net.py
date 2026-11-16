"""Polite HTTP: robots.txt checks, per-host rate limits, retries and a SQLite response cache."""
from __future__ import annotations

import gzip
import json
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from datetime import datetime, timedelta, timezone

from .db import now_iso


class FetchError(RuntimeError):
    pass


class RobotsDisallowed(FetchError):
    pass


class HttpClient:
    """All adapters fetch through this, so politeness rules live in one place."""

    def __init__(self, conn: sqlite3.Connection | None, user_agent: str, cache_ttl_hours: float = 20,
                 min_interval: float = 1.0, timeout: float = 30, offline: bool = False,
                 strict_robots: bool = False):
        self.conn = conn
        self.strict_robots = strict_robots
        # Hosts serving a documented public API. Their published API terms and rate limits
        # govern access; robots.txt (written for crawlers) is applied only in strict mode.
        self.api_hosts: set[str] = set()
        self.user_agent = user_agent
        self.ttl = timedelta(hours=cache_ttl_hours)
        self.min_interval = min_interval
        self.timeout = timeout
        self.offline = offline
        self._last_hit: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self._host_intervals: dict[str, float] = {}
        self.requests_made = 0
        self.cache_hits = 0

    # -- politeness -------------------------------------------------------
    def set_host_interval(self, host: str, seconds: float) -> None:
        self._host_intervals[host] = max(seconds, self._host_intervals.get(host, 0))

    def register_api(self, host: str, min_interval: float | None = None) -> None:
        self.api_hosts.add(host)
        if min_interval:
            self.set_host_interval(host, min_interval)

    def _wait_turn(self, host: str) -> None:
        interval = self._host_intervals.get(host, self.min_interval)
        elapsed = time.monotonic() - self._last_hit.get(host, 0)
        if elapsed < interval:
            time.sleep(interval - elapsed)
        self._last_hit[host] = time.monotonic()

    def allowed(self, url: str) -> bool:
        """robots.txt check. API hosts without a robots.txt are allowed."""
        parts = urllib.parse.urlsplit(url)
        base = f"{parts.scheme}://{parts.netloc}"
        if base not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            try:
                body = self._raw_get(base + "/robots.txt", accept="text/plain", check_robots=False)
                rp.parse(body.decode("utf-8", "replace").splitlines())
            except FetchError:
                rp = None  # no robots.txt (or unreachable): treat as allowed
            self._robots[base] = rp
        rp = self._robots[base]
        if rp is None:
            return True
        delay = rp.crawl_delay(self.user_agent)
        if delay:
            self.set_host_interval(parts.netloc, float(delay))
        return rp.can_fetch(self.user_agent, url)

    def needs_robots_check(self, url: str) -> bool:
        return self.strict_robots or urllib.parse.urlsplit(url).netloc not in self.api_hosts

    # -- cache --------------------------------------------------------------
    def _cached(self, url: str):
        if self.conn is None:
            return None
        row = self.conn.execute("SELECT fetched_at, body FROM http_cache WHERE url=? AND status=200", (url,)).fetchone()
        if not row:
            return None
        fetched = datetime.fromisoformat(row["fetched_at"])
        if self.offline or datetime.now(timezone.utc) - fetched < self.ttl:
            return row["body"], row["fetched_at"]
        return None

    def _store(self, url: str, body: bytes, content_type: str) -> str:
        ts = now_iso()
        if self.conn is not None:
            self.conn.execute(
                "INSERT OR REPLACE INTO http_cache (url, fetched_at, status, content_type, body) VALUES (?,?,?,?,?)",
                (url, ts, 200, content_type, body),
            )
            self.conn.commit()
        return ts

    # -- fetching -----------------------------------------------------------
    def _raw_get(self, url: str, accept: str, headers: dict | None = None, check_robots: bool = True) -> bytes:
        if self.offline:
            raise FetchError(f"offline mode and no cached copy of {url}")
        if check_robots and self.needs_robots_check(url) and not self.allowed(url):
            raise RobotsDisallowed(f"robots.txt disallows {url}")
        host = urllib.parse.urlsplit(url).netloc
        hdrs = {"User-Agent": self.user_agent, "Accept": accept, "Accept-Encoding": "gzip"}
        hdrs.update(headers or {})
        last_err = None
        for attempt in range(4):
            self._wait_turn(host)
            req = urllib.request.Request(url, headers=hdrs)
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    self.requests_made += 1
                    body = resp.read()
                    if resp.headers.get("Content-Encoding") == "gzip":
                        body = gzip.decompress(body)
                    return body
            except urllib.error.HTTPError as exc:
                last_err = exc
                if exc.code in (429, 502, 503, 504) or (exc.code == 403 and "rate limit" in str(exc.read()[:500]).lower()):
                    retry_after = exc.headers.get("Retry-After")
                    delay = float(retry_after) if retry_after and retry_after.isdigit() else 2 ** (attempt + 1)
                    time.sleep(min(delay, 60))
                    continue
                raise FetchError(f"HTTP {exc.code} for {url}") from exc
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                last_err = exc
                time.sleep(2 ** attempt)
        raise FetchError(f"giving up on {url}: {last_err}")

    def get(self, url: str, params: dict | None = None, accept: str = "application/json",
            headers: dict | None = None, use_cache: bool = True) -> tuple[bytes, str]:
        """Returns (body, retrieved_at). retrieved_at is when the bytes were actually fetched."""
        if params:
            url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params, doseq=True)
        if use_cache:
            hit = self._cached(url)
            if hit:
                self.cache_hits += 1
                return hit
        body = self._raw_get(url, accept=accept, headers=headers)
        ts = self._store(url, body, accept) if use_cache else now_iso()
        return body, ts

    def get_json(self, url: str, params: dict | None = None, headers: dict | None = None):
        body, ts = self.get(url, params=params, headers=headers)
        return json.loads(body.decode("utf-8")), ts

    def get_text(self, url: str, params: dict | None = None, accept: str = "application/rss+xml, text/xml, */*"):
        body, ts = self.get(url, params=params, accept=accept)
        return body.decode("utf-8", "replace"), ts


class FixtureClient(HttpClient):
    """Serves recorded responses from tests/fixtures. Used by adapter tests; never touches the network."""

    def __init__(self, routes: dict[str, str], fixtures_dir, retrieved_at: str = "2026-11-16T12:00:00+00:00"):
        super().__init__(conn=None, user_agent="fixture", offline=True)
        self.routes = routes  # substring of URL -> fixture filename
        self.fixtures_dir = fixtures_dir
        self.retrieved_at = retrieved_at
        self.requested: list[str] = []

    def get(self, url, params=None, accept="application/json", headers=None, use_cache=True):
        if params:
            url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params, doseq=True)
        self.requested.append(url)
        for needle, filename in self.routes.items():
            if needle in url:
                return (self.fixtures_dir / filename).read_bytes(), self.retrieved_at
        raise FetchError(f"no fixture for {url}")
