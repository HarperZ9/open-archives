# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Zain Dana Harper
"""Wikimedia Commons (MediaWiki Action API) and the Library of Congress JSON API.

Commons docs: https://commons.wikimedia.org/wiki/Commons:API and
https://www.mediawiki.org/wiki/API:Imageinfo (extmetadata carries licence).
LoC docs: https://www.loc.gov/apis/json-and-yaml/ (append fo=json).
Both keyless. Commons asks for a descriptive User-Agent with contact.
"""
from __future__ import annotations

import re

from ..model import Item, MediaFile, first
from ..net import Http, qs
from .base import Adapter, Query

_FILETYPE = {"image": "bitmap", "texture": "bitmap", "video": "video",
             "audio": "audio", "text": "office"}
_MIME_MEDIA = (("image/svg", "image"), ("image/", "image"), ("video/", "video"),
               ("audio/", "audio"), ("application/ogg", "audio"),
               ("application/pdf", "text"))


def _strip(html: str | None) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html or "")).strip()


class WikimediaCommons(Adapter):
    name = "wikimedia_commons"
    label = "Wikimedia Commons"
    docs = "https://www.mediawiki.org/wiki/API:Imageinfo"
    media = ("image", "texture", "video", "audio", "text")

    def search(self, http: Http, q: Query) -> list[Item]:
        types = sorted({_FILETYPE[m] for m in q.media if m in _FILETYPE})
        text = q.text + (" filetype:" + "|".join(types) if types else "")
        url = "https://commons.wikimedia.org/w/api.php?" + qs({
            "action": "query", "format": "json", "generator": "search",
            "gsrsearch": text, "gsrnamespace": 6, "gsrlimit": min(q.limit, 50),
            "prop": "imageinfo", "iiprop": "url|extmetadata|size|mime",
            "iiurlwidth": 800})
        pages = http.json(url).get("query", {}).get("pages", {})
        ordered = sorted(pages.values(), key=lambda p: p.get("index", 0))
        return self._rank([i for i in (self.to_item(p) for p in ordered) if i])

    def to_item(self, page: dict) -> Item | None:
        info = (page.get("imageinfo") or [None])[0]
        if not info:
            return None
        meta = {k: v.get("value") for k, v in info.get("extmetadata", {}).items()}
        mime = info.get("mime", "")
        mtype = next((m for prefix, m in _MIME_MEDIA if mime.startswith(prefix)), "image")
        title = page["title"].removeprefix("File:")
        rights = " ".join(filter(None, [meta.get("LicenseShortName"), meta.get("UsageTerms")]))
        return Item(
            source=self.name, id=title, title=_strip(meta.get("ObjectName")) or title,
            media_type=mtype, landing_url=info.get("descriptionurl", ""),
            creator=_strip(meta.get("Artist")) or None,
            date=_strip(meta.get("DateTimeOriginal")) or None,
            description=_strip(meta.get("ImageDescription")),
            subjects=[c for c in (meta.get("Categories") or "").split("|") if c],
            files=[MediaFile(url=info["url"], size=info.get("size"), mime=mime,
                             name=title)],
            thumb_url=info.get("thumburl"), licence_url=meta.get("LicenseUrl"),
            rights_raw=rights, extra={"credit": _strip(meta.get("Credit"))})


_LOC_PATH = {"image": "photos", "texture": "photos", "video": "film-and-videos",
             "audio": "audio", "text": "books"}


class LibraryOfCongress(Adapter):
    name = "loc"
    label = "Library of Congress"
    docs = "https://www.loc.gov/apis/json-and-yaml/"
    media = ("image", "texture", "video", "audio", "text")
    note = ("Most LoC items say 'No known restrictions on publication', which is "
            "not a licence: they gate to reference-only (class nkr) until a person "
            "confirms public domain status.")

    def search(self, http: Http, q: Query) -> list[Item]:
        wanted = [m for m in q.media if m in _LOC_PATH] or ["image"]
        items: list[Item] = []
        for path in dict.fromkeys(_LOC_PATH[m] for m in wanted):
            params = {"q": q.text, "fo": "json", "c": min(q.limit, 50)}
            if q.year_from or q.year_to:
                params["dates"] = f"{q.year_from or 1000}/{q.year_to or 2100}"
            data = http.json(f"https://www.loc.gov/{path}/?" + qs(params))
            items += [self.to_item(r, path) for r in data.get("results", [])]
        return self._rank(items)

    def to_item(self, r: dict, path: str) -> Item:
        detail = r.get("item") or {}
        # Drop LoC's generic format icons (for example group-of-images.svg).
        images = [u.split("#")[0] for u in (r.get("image_url") or []) if "/static/" not in u]
        mtype = {"photos": "image", "film-and-videos": "video", "audio": "audio",
                 "books": "text"}[path]
        rights = detail.get("rights_advisory") or first(r.get("rights")) or ""
        creators = detail.get("contributors") or detail.get("creators") or []
        files = [MediaFile(url=images[-1], kind="large")] if images and mtype == "image" else []
        return Item(
            source=self.name, id=r.get("id", r.get("url", "")).rstrip("/").split("/")[-1],
            title=str(r.get("title") or ""), media_type=mtype,
            landing_url=r.get("url") or r.get("id", ""),
            creator=str(first(creators)) if creators else None, date=r.get("date"),
            description=str(first(r.get("description")) or ""),
            subjects=[str(s) for s in (r.get("subject") or [])][:20],
            files=files, thumb_url=images[0] if images else None,
            rights_raw=str(first(rights) if isinstance(rights, list) else rights))
