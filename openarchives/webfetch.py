# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Zain Dana Harper
"""Fetch from any web address, politely, with the rights basis recorded.

Rules: robots.txt is honoured for our User-Agent (a disallow refuses the
fetch); site terms cannot be read by a program, so the receipt records
whether a person reviewed them. Licence words found on a page are kept as a
hint only. The basis stays reference-only until a person confirms a licence
or records another basis (fair use, licensed) with a reason.
"""
from __future__ import annotations

import html
import logging
import re
import urllib.parse
import urllib.robotparser
from pathlib import Path

from . import licence as lic
from .library import Library, safe_name
from .model import Item, MediaFile
from .net import USER_AGENT, Http, HttpError

log = logging.getLogger("openarchives.web")
_ROBOTS: dict[str, urllib.robotparser.RobotFileParser] = {}
_MEDIA_RE = re.compile(r'<(?:img|video|audio|source)[^>]+src=["\']([^"\']+)["\']', re.I)
_OG_RE = re.compile(r'<meta[^>]+property=["\']og:(?:image|video|audio)["\'][^>]+content=["\']([^"\']+)', re.I)
_LICENSE_RE = re.compile(r'rel=["\']license["\'][^>]*href=["\']([^"\']+)|href=["\']([^"\']+)["\'][^>]*rel=["\']license', re.I)
_CC_RE = re.compile(r'https?://creativecommons\.org/(?:licenses|publicdomain)/[a-z0-9./-]+', re.I)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)


class RobotsRefused(RuntimeError):
    pass


def robots_allows(http: Http, url: str) -> tuple[bool, str]:
    parts = urllib.parse.urlsplit(url)
    base = f"{parts.scheme}://{parts.netloc}"
    rp = _ROBOTS.get(base)
    if rp is None:
        rp = urllib.robotparser.RobotFileParser()
        try:
            rp.parse(http.text(base + "/robots.txt").splitlines())
        except HttpError as exc:
            if exc.status in (401, 403):
                rp.parse(["User-agent: *", "Disallow: /"])   # RFC 9309: treat as full disallow
            else:
                rp.parse([])                                  # 404 and similar: no rules
        _ROBOTS[base] = rp
    ok = rp.can_fetch(USER_AGENT, url)
    return ok, f"robots.txt at {base}: {'allowed' if ok else 'disallowed'}"


def licence_hints(page: str) -> list[str]:
    hints = [a or b for a, b in _LICENSE_RE.findall(page)]
    hints += _CC_RE.findall(page)
    if re.search(r"public domain", page, re.I):
        hints.append("page text mentions 'public domain'")
    return list(dict.fromkeys(hints))[:10]


def media_links(page: str, base: str, limit: int) -> list[str]:
    found = _OG_RE.findall(page) + _MEDIA_RE.findall(page)
    urls = [urllib.parse.urljoin(base, html.unescape(u)) for u in found if not u.startswith("data:")]
    return list(dict.fromkeys(urls))[:limit]


def fetch(http: Http, lib: Library, url: str, licence_claim: str | None = None,
          basis_claim: str | None = None, reason: str = "", terms_note: str = "",
          media_limit: int = 0, tag: str = "web") -> Path:
    ok, robots_note = robots_allows(http, url)
    if not ok:
        raise RobotsRefused(robots_note)
    host = urllib.parse.urlsplit(url).netloc
    with http.open(url, {"Accept": "*/*"}) as resp:
        ctype = resp.headers.get("Content-Type", "")
    is_html = "html" in ctype
    targets, hints, title = [url], [], url
    if is_html:
        page = http.text(url)
        hints = licence_hints(page)
        m = _TITLE_RE.search(page)
        title = html.unescape(m.group(1).strip()) if m else url
        targets = [url] + media_links(page, url, media_limit)
    items = []
    for target in targets:
        allowed, note = robots_allows(http, target)
        if not allowed:
            log.warning("skipping %s: %s", target, note)
            continue
        cls = lic.normalise(licence_claim) if licence_claim else lic.UNKNOWN
        basis = basis_claim or lic.basis_for(cls)
        name = target.split("?")[0].rstrip("/").rsplit("/", 1)[-1] or "index.html"
        if target == url and is_html and not name.endswith((".html", ".htm")):
            name += ".html"
        it = Item(source="web", id=f"{host}/{safe_name(name)}", title=title if target == url else name,
                  media_type="text" if (target == url and is_html) else _guess(name),
                  landing_url=url, files=[MediaFile(url=target, name=name)],
                  rights_raw=licence_claim or "", extra={
                      "robots": note, "licence_hints": hints,
                      "licence_source": "author claim" if licence_claim else "none; hints only",
                      "terms_review": terms_note or "site terms not reviewed by a person",
                      "basis_reason": reason or ("licence gate" if licence_claim else
                                                 "no confirmed licence: reference-only")})
        it.finalise()
        it.basis = basis
        if basis in (lic.FAIR_USE, lic.LICENSED) and len(reason) < 20:
            raise ValueError(f"basis {basis} needs a written reason")
        items.append(it)
    from .library import GatherPlan
    return lib.gather(http, items, GatherPlan(files_per_item=1), tag,
                      {"url": url, "licence_claim": licence_claim, "basis_claim": basis_claim})


def _guess(name: str) -> str:
    ext = Path(name).suffix.lower()
    for kind, exts in (("image", {".jpg", ".jpeg", ".png", ".gif", ".webp", ".tif", ".tiff", ".svg"}),
                       ("video", {".mp4", ".webm", ".ogv", ".mov", ".mkv"}),
                       ("audio", {".mp3", ".wav", ".ogg", ".flac", ".m4a", ".opus"}),
                       ("font", {".ttf", ".otf", ".woff", ".woff2"}),
                       ("model3d", {".glb", ".gltf", ".obj", ".fbx", ".ply", ".stl"})):
        if ext in exts:
            return kind
    return "dataset"
