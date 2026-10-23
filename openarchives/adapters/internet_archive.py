# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Zain Dana Harper
"""Internet Archive: advancedsearch, metadata and download APIs.

Docs: https://archive.org/developers/ (advancedsearch, metadata, download).
Keyless. Presets cover Prelinger films, 78rpm records (George Blood and the
broader 78rpm collection), live concerts (etree) and Musopen recordings.
"""
from __future__ import annotations

import urllib.parse

from ..model import Item, MediaFile, first, parse_year
from ..net import Http, qs
from .base import Adapter, Query

BASE = "https://archive.org"
_IA_TO_MEDIA = {"movies": "video", "audio": "audio", "etree": "audio",
                "image": "image", "texts": "text", "data": "dataset"}
_MEDIA_TO_IA = {"video": "movies", "audio": "(audio OR etree)", "image": "image",
                "text": "texts", "dataset": "data", "texture": "image"}
FIELDS = ["identifier", "title", "creator", "date", "year", "description",
          "licenseurl", "rights", "mediatype", "subject", "collection"]

# Preferred derivative formats, smallest useful first.
_PREFER = {
    "video": ["512Kb MPEG4", "h.264 IA", "h.264", "MPEG4", "Ogg Video"],
    "audio": ["VBR MP3", "128Kbps MP3", "64Kbps MP3", "MP3", "Ogg Vorbis", "Flac"],
    "image": ["JPEG", "JPEG 2000", "PNG", "TIFF"],
    "text": ["Text PDF", "Additional Text PDF", "DjVuTXT", "EPUB"],
    "dataset": [],
}


class InternetArchive(Adapter):
    name = "internet_archive"
    label = "Internet Archive (all collections)"
    docs = "https://archive.org/developers/"
    media = ("video", "audio", "image", "text", "dataset", "texture")
    collection_clause = ""

    def build_query(self, q: Query) -> str:
        parts = [f"({q.text})"]
        if self.collection_clause:
            parts.append(self.collection_clause)
        wanted = [_MEDIA_TO_IA[m] for m in q.media if m in _MEDIA_TO_IA]
        if wanted and not self.collection_clause:
            parts.append("mediatype:(" + " OR ".join(sorted(set(wanted))) + ")")
        if q.year_from or q.year_to:
            parts.append(f"year:[{q.year_from or 1000} TO {q.year_to or 2100}]")
        return " AND ".join(parts)

    def search(self, http: Http, q: Query) -> list[Item]:
        url = f"{BASE}/advancedsearch.php?" + qs({
            "q": self.build_query(q), "fl[]": FIELDS,
            "rows": q.limit, "page": 1, "output": "json"})
        docs = http.json(url)["response"]["docs"]
        return self._rank([self.to_item(d) for d in docs])

    def to_item(self, d: dict) -> Item:
        ident = d["identifier"]
        mtype = _IA_TO_MEDIA.get(d.get("mediatype", ""), "dataset")
        subjects = d.get("subject") or []
        return Item(
            source=self.name, id=ident, title=str(first(d.get("title")) or ident),
            media_type=mtype, landing_url=f"{BASE}/details/{ident}",
            creator=first(d.get("creator")), date=str(d.get("date") or d.get("year") or ""),
            description=d.get("description") or "",
            subjects=subjects if isinstance(subjects, list) else [subjects],
            thumb_url=f"{BASE}/services/img/{ident}",
            licence_url=d.get("licenseurl"), rights_raw=str(first(d.get("rights")) or ""),
            extra={"collection": d.get("collection")})

    def resolve(self, http: Http, item: Item) -> Item:
        meta = http.json(f"{BASE}/metadata/{urllib.parse.quote(item.id)}")
        md = meta.get("metadata", {})
        item.licence_url = item.licence_url or md.get("licenseurl")
        item.rights_raw = item.rights_raw or str(first(md.get("rights")) or "")
        item.files = pick_files(item.id, meta.get("files", []), item.media_type)
        item.attribution = ""
        return item.finalise()


def pick_files(ident: str, files: list[dict], media_type: str, max_files: int = 3) -> list[MediaFile]:
    prefs = _PREFER.get(media_type, [])
    by_format: dict[str, list[dict]] = {}
    for f in files:
        by_format.setdefault(f.get("format", ""), []).append(f)
    for fmt in prefs:
        if fmt in by_format:
            chosen = sorted(by_format[fmt], key=lambda f: f["name"])[:max_files]
            return [_mf(ident, f) for f in chosen]
    originals = [f for f in files if f.get("source") == "original"
                 and not f["name"].endswith((".xml", ".sqlite", ".torrent"))]
    return [_mf(ident, f) for f in originals[:1]]


def _mf(ident: str, f: dict) -> MediaFile:
    url = f"{BASE}/download/{urllib.parse.quote(ident)}/{urllib.parse.quote(f['name'])}"
    size = int(f["size"]) if str(f.get("size", "")).isdigit() else None
    return MediaFile(url=url, kind=f.get("source", "original"), size=size,
                     name=f["name"].split("/")[-1], mime=f.get("format"))


class Prelinger(InternetArchive):
    name = "ia_prelinger"
    label = "Internet Archive: Prelinger Archives (ephemeral films)"
    media = ("video",)
    collection_clause = "collection:prelinger"


class SeventyEight(InternetArchive):
    name = "ia_78rpm"
    label = "Internet Archive: 78rpm records (Great 78 Project, George Blood)"
    media = ("audio",)
    collection_clause = "(collection:georgeblood OR collection:78rpm)"
    note = "Most 78s carry no licence statement: they gate to reference-only."

    def to_item(self, d: dict) -> Item:
        it = super().to_item(d)
        year = parse_year(it.date)
        if year:
            it.extra["rights_hint"] = us_recording_hint(year)
        return it


def us_recording_hint(year: int, today_year: int | None = None) -> str:
    """US status hint for a published sound recording (Music Modernization Act:
    pre-1923 recordings entered the public domain in 2022; 1923-1946 recordings
    enter it 100 years after publication). A hint for a person to confirm, never
    a gate decision; the composition and other countries are separate questions."""
    import time as _t
    now = today_year or int(_t.strftime("%Y"))
    if year < 1923 or year + 100 < now:
        return (f"recording published {year}: likely public domain in the US under the "
                "Music Modernization Act; check the composition and the release date")
    return f"recording published {year}: likely still protected in the US"


class Etree(InternetArchive):
    name = "ia_etree"
    label = "Internet Archive: Live Music Archive (etree)"
    media = ("audio",)
    collection_clause = "collection:etree"
    note = "Trade-friendly live recordings, mostly non-commercial terms."
    default = False


class Musopen(InternetArchive):
    name = "musopen"
    label = "Musopen recordings (Internet Archive mirror)"
    media = ("audio",)
    collection_clause = "collection:musopen"
    note = ("Musopen has no public search API; its public domain recordings are "
            "mirrored in the Internet Archive 'musopen' collection.")
