"""Polite HTTP client: obeys robots.txt, rate-limits per host, retries, and caches to disk.

Every page is cached under data/cache/, so re-runs are free and an interrupted scrape resumes.
"""
from __future__ import annotations

import hashlib
import random
import time
from pathlib import Path
from urllib import robotparser
from urllib.parse import urlparse

import requests

USER_AGENT = "soccer-eras-research/0.1 (personal sports research{contact}) python-requests"


class RobotsDisallowed(Exception):
    pass


class Blocked(Exception):
    """The site refused scripted requests (403 / bot challenge)."""


class FetchFailed(Exception):
    """A page couldn't be fetched after retries (network trouble or server errors)."""


class PoliteSession:
    def __init__(self, cache_dir: Path, delay: float = 3.0, jitter: float = 1.5,
                 contact: str | None = None, max_retries: int = 4):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.delay, self.jitter, self.max_retries = delay, jitter, max_retries
        self.s = requests.Session()
        ua = USER_AGENT.format(contact=f"; {contact}" if contact else "")
        self.s.headers.update({"User-Agent": ua, "Accept-Language": "en"})
        self._robots: dict[str, robotparser.RobotFileParser] = {}
        self._last: dict[str, float] = {}

    def _cache_path(self, url: str) -> Path:
        host = urlparse(url).netloc.replace(":", "_")
        return self.cache_dir / host / (hashlib.sha1(url.encode()).hexdigest() + ".html")

    def allowed(self, url: str) -> bool:
        p = urlparse(url)
        base = f"{p.scheme}://{p.netloc}"
        if base not in self._robots:
            rp = robotparser.RobotFileParser()
            try:
                r = self.s.get(base + "/robots.txt", timeout=20)
                rp.parse(r.text.splitlines() if r.ok else [])
            except requests.RequestException:
                rp.parse([])
            self._robots[base] = rp
        return self._robots[base].can_fetch(self.s.headers["User-Agent"], url)

    def _wait(self, host: str) -> None:
        gap = self.delay + random.uniform(0, self.jitter)
        elapsed = time.time() - self._last.get(host, 0)
        if elapsed < gap:
            time.sleep(gap - elapsed)
        self._last[host] = time.time()

    def get(self, url: str, use_cache: bool = True) -> str | None:
        """Return page HTML, or None on 404. Raises RobotsDisallowed if robots.txt forbids it."""
        cp = self._cache_path(url)
        if use_cache and cp.exists():
            text = cp.read_text(encoding="utf-8")
            return None if text == "__404__" else text
        if not self.allowed(url):
            raise RobotsDisallowed(url)
        host = urlparse(url).netloc
        last = "unknown error"
        for attempt in range(self.max_retries):
            self._wait(host)
            try:
                r = self.s.get(url, timeout=30)
            except requests.RequestException as e:
                last = f"network error ({type(e).__name__}) - the connection dropped or was refused"
                time.sleep(5 * (attempt + 1))
                continue
            if r.status_code == 404:
                cp.parent.mkdir(parents=True, exist_ok=True)
                cp.write_text("__404__", encoding="utf-8")
                return None
            if r.status_code in (401, 403) or _is_bot_challenge(r):
                # The site is refusing scripted requests. Retrying would be impolite and won't help.
                raise Blocked(f"{url} -> HTTP {r.status_code}: the site is refusing automated requests")
            if r.status_code in (429, 503):
                last = f"HTTP {r.status_code} (site asked us to slow down)"
                wait = int(r.headers.get("Retry-After", 30 * (attempt + 1)))
                time.sleep(min(wait, 300))
                continue
            if r.ok:
                cp.parent.mkdir(parents=True, exist_ok=True)
                cp.write_text(r.text, encoding="utf-8")
                return r.text
            last = f"HTTP {r.status_code}"
            time.sleep(5 * (attempt + 1))
        raise FetchFailed(f"{url} -> {last} (after {self.max_retries} tries)")


def _is_bot_challenge(r: requests.Response) -> bool:
    if r.status_code not in (403, 503):
        return False
    head = r.text[:3000].lower()
    return "just a moment" in head or "cf-chl" in head or "captcha" in head or "access denied" in head
