# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Zain Dana Harper
"""HTTP client: polite User-Agent, per-host rate limit, retries, size caps.

Standard library only. Every request names the tool in its User-Agent, waits
a minimum interval per host, and backs off on 429 and 5xx responses.
"""
from __future__ import annotations

import hashlib
import http.client
import json
import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import __version__

log = logging.getLogger("openarchives.net")

USER_AGENT = (
    f"open-archives/{__version__} "
    "(open media and reference gatherer; https://github.com/HarperZ9)"
)
DEFAULT_INTERVAL = 1.0  # seconds between requests to one host
HOST_INTERVALS = {
    "commons.wikimedia.org": 0.5,
    "upload.wikimedia.org": 0.5,
    "www.loc.gov": 3.0,  # LoC asks for gentle use; it rate-limits bursts
    "tile.loc.gov": 1.0,
    "api.openverse.org": 1.5,
    "gutendex.com": 2.0,
}


# Headers some APIs ask for in their docs (AIC: https://api.artic.edu/docs/).
HOST_HEADERS = {
    "api.artic.edu": {"AIC-User-Agent": USER_AGENT},
    "www.artic.edu": {"AIC-User-Agent": USER_AGENT},
}


class HttpError(RuntimeError):
    def __init__(self, url: str, status: int, body: str = ""):
        super().__init__(f"HTTP {status} for {url}: {body[:200]}")
        self.url = url
        self.status = status
        self.body = body


class SizeCapExceeded(RuntimeError):
    pass


class Http:
    """Shared client. Thread-safe per-host pacing."""

    def __init__(self, user_agent: str = USER_AGENT, timeout: float = 45.0,
                 retries: int = 3, interval_scale: float = 1.0):
        self.user_agent = user_agent
        self.timeout = timeout
        self.retries = retries
        self.interval_scale = interval_scale
        self._lock = threading.Lock()
        self._next_ok: dict[str, float] = {}
        self.requests_made = 0

    def _pace(self, url: str) -> None:
        host = urllib.parse.urlsplit(url).hostname or ""
        gap = HOST_INTERVALS.get(host, DEFAULT_INTERVAL) * self.interval_scale
        with self._lock:
            now = time.monotonic()
            start = max(now, self._next_ok.get(host, 0.0))
            self._next_ok[host] = start + gap
        if start > now:
            time.sleep(start - now)

    def open(self, url: str, headers: dict | None = None, method: str = "GET"):
        hdrs = {"User-Agent": self.user_agent, "Accept": "application/json, */*"}
        hdrs.update(HOST_HEADERS.get(urllib.parse.urlsplit(url).hostname or "", {}))
        hdrs.update(headers or {})
        delay = 2.0
        for attempt in range(self.retries + 1):
            self._pace(url)
            req = urllib.request.Request(url, headers=hdrs, method=method)
            try:
                self.requests_made += 1
                return urllib.request.urlopen(req, timeout=self.timeout)
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", "replace")
                retryable = exc.code == 429 or exc.code >= 500
                if not retryable or attempt == self.retries:
                    raise HttpError(url, exc.code, body) from exc
                wait = float(exc.headers.get("Retry-After") or delay)
                log.warning("HTTP %s from %s, retry in %.0fs", exc.code, url, wait)
                time.sleep(min(wait, 60))
                delay *= 2
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                if attempt == self.retries:
                    raise HttpError(url, 0, str(exc)) from exc
                log.warning("network error %s on %s, retry in %.0fs", exc, url, delay)
                time.sleep(delay)
                delay *= 2
        raise AssertionError("unreachable")

    def text(self, url: str, headers: dict | None = None) -> str:
        for attempt in range(self.retries + 1):
            try:
                with self.open(url, headers) as resp:
                    charset = resp.headers.get_content_charset() or "utf-8"
                    return resp.read().decode(charset, "replace")
            except (http.client.IncompleteRead, ConnectionError, TimeoutError) as exc:
                if attempt == self.retries:
                    raise HttpError(url, 0, f"body read failed: {exc}") from exc
                log.warning("body read failed on %s (%s), retrying", url, type(exc).__name__)
                time.sleep(2.0 * (attempt + 1))
        raise AssertionError("unreachable")

    def json(self, url: str, headers: dict | None = None):
        return json.loads(self.text(url, headers))

    def download(self, url: str, dest: Path, max_bytes: int,
                 headers: dict | None = None) -> tuple[int, str]:
        """Stream url to dest. Returns (bytes, sha256). Removes partial files."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".part")
        digest = hashlib.sha256()
        total = 0
        try:
            with self.open(url, headers) as resp, open(tmp, "wb") as fh:
                declared = resp.headers.get("Content-Length")
                if declared and int(declared) > max_bytes:
                    raise SizeCapExceeded(f"{url} declares {declared} bytes > cap {max_bytes}")
                while chunk := resp.read(1 << 16):
                    total += len(chunk)
                    if total > max_bytes:
                        raise SizeCapExceeded(f"{url} exceeded cap {max_bytes} bytes")
                    digest.update(chunk)
                    fh.write(chunk)
            tmp.replace(dest)
        except BaseException:
            log.error("download failed for %s, removing partial file", url)
            tmp.unlink(missing_ok=True)
            raise
        return total, digest.hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def qs(params: dict) -> str:
    """urlencode that drops None values and repeats list values."""
    clean = {k: v for k, v in params.items() if v is not None}
    return urllib.parse.urlencode(clean, doseq=True)
