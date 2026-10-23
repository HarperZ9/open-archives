# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Zain Dana Harper
"""Keyless open media APIs: NASA, Openverse, Wellcome, Project Gutenberg, Zenodo.

NASA: https://images.nasa.gov/docs/images.nasa.gov_api_docs.pdf
Openverse: https://api.openverse.org/v1/ (anonymous use is rate-limited)
Wellcome: https://developers.wellcomecollection.org/docs/catalogue
Gutenberg via Gutendex: https://gutendex.com/ (Project Gutenberg has no search API)
Zenodo: https://developers.zenodo.org/
"""
from __future__ import annotations

import urllib.parse

from ..model import Item, MediaFile
from ..net import Http, qs
from .base import Adapter, Query

NASA_RIGHTS = ("public domain: NASA-produced media are generally not subject to "
               "US copyright (NASA Images and Media Usage Guidelines)")


class Nasa(Adapter):
    name = "nasa"
    label = "NASA Image and Video Library"
    docs = "https://images.nasa.gov/docs/images.nasa.gov_api_docs.pdf"
    media = ("image", "video", "audio", "texture")

    def search(self, http: Http, q: Query) -> list[Item]:
        kinds = sorted({{"texture": "image"}.get(m, m) for m in q.media
                        if m in self.media}) or ["image", "video", "audio"]
        url = "https://images-api.nasa.gov/search?" + qs({
            "q": q.text, "media_type": ",".join(kinds), "page_size": min(q.limit, 100),
            "year_start": q.year_from, "year_end": q.year_to})
        items = http.json(url).get("collection", {}).get("items", [])
        return self._rank([self.to_item(i) for i in items[: q.limit]])

    def to_item(self, raw: dict) -> Item:
        d = raw["data"][0]
        thumb = next((l["href"] for l in raw.get("links", []) if l.get("rel") == "preview"), None)
        third_party = d.get("secondary_creator") or d.get("photographer") or ""
        rights = NASA_RIGHTS
        if third_party and "nasa" not in third_party.lower():
            rights = f"third-party credit ({third_party}); rights must be checked"
        return Item(
            source=self.name, id=d["nasa_id"], title=d.get("title") or d["nasa_id"],
            media_type=d.get("media_type", "image"),
            landing_url=f"https://images.nasa.gov/details/{urllib.parse.quote(d['nasa_id'])}",
            creator=third_party or d.get("center"), date=d.get("date_created"),
            description=d.get("description") or "", subjects=d.get("keywords") or [],
            thumb_url=thumb, rights_raw=rights, extra={"assets": raw.get("href")})

    def resolve(self, http: Http, item: Item) -> Item:
        urls = http.json(item.extra["assets"])
        pick = {"image": ("~large.jpg", "~orig.jpg", "~medium.jpg"),
                "video": ("~mobile.mp4", "~small.mp4", "~medium.mp4", "~orig.mp4"),
                "audio": ("~128k.mp3", ".mp3", ".m4a", ".wav")}.get(item.media_type, ())
        for suffix in pick:
            hit = next((u for u in urls if u.lower().endswith(suffix)), None)
            if hit:
                item.files = [MediaFile(url=hit.replace("http://", "https://").replace(" ", "%20"))]
                break
        return item


class Openverse(Adapter):
    name = "openverse"
    label = "Openverse (CC images and audio, includes Freesound and Flickr)"
    docs = "https://api.openverse.org/v1/"
    media = ("image", "texture", "audio")

    def search(self, http: Http, q: Query) -> list[Item]:
        items: list[Item] = []
        kinds = []
        if q.wants("image") or q.wants("texture"):
            kinds.append("images")
        if q.wants("audio"):
            kinds.append("audio")
        for kind in kinds:
            url = f"https://api.openverse.org/v1/{kind}/?" + qs(
                {"q": q.text, "page_size": min(q.limit, 20)})
            items += [self.to_item(r, kind) for r in http.json(url).get("results", [])]
        return self._rank(items)

    def to_item(self, r: dict, kind: str) -> Item:
        return Item(
            source=self.name, id=r["id"], title=r.get("title") or r["id"],
            media_type="image" if kind == "images" else "audio",
            landing_url=r.get("foreign_landing_url") or "", creator=r.get("creator"),
            subjects=[t["name"] for t in (r.get("tags") or []) if t.get("name")],
            files=[MediaFile(url=r["url"], size=r.get("filesize"))] if r.get("url") else [],
            thumb_url=r.get("thumbnail"), licence_url=r.get("license_url"),
            rights_raw=f"{r.get('license', '')} {r.get('license_version', '')}".strip(),
            attribution=r.get("attribution") or "",
            extra={"provider": r.get("provider"), "duration_ms": r.get("duration")})


class Wellcome(Adapter):
    name = "wellcome"
    label = "Wellcome Collection images"
    docs = "https://developers.wellcomecollection.org/docs/catalogue"
    media = ("image", "texture")

    def search(self, http: Http, q: Query) -> list[Item]:
        url = "https://api.wellcomecollection.org/catalogue/v2/images?" + qs(
            {"query": q.text, "pageSize": min(q.limit, 100),
             "include": "source.contributors"})
        return self._rank([self.to_item(r) for r in http.json(url).get("results", [])])

    def to_item(self, r: dict) -> Item:
        loc = (r.get("locations") or [{}])[0]
        lic_ = loc.get("license") or {}
        base = loc.get("url", "").removesuffix("/info.json")
        src = r.get("source") or {}
        contrib = src.get("contributors") or []
        prod = src.get("production") or []
        date = next((d.get("label") for p in prod for d in p.get("dates", [])), None)
        return Item(
            source=self.name, id=r["id"], title=src.get("title") or r["id"],
            media_type="image", landing_url=f"https://wellcomecollection.org/works/{src.get('id', '')}",
            creator=(contrib[0].get("agent") or {}).get("label") if contrib else None,
            date=date, files=[MediaFile(url=f"{base}/full/!2000,2000/0/default.jpg")] if base else [],
            thumb_url=f"{base}/full/!400,400/0/default.jpg" if base else None,
            licence_url=lic_.get("url"), rights_raw=f"{lic_.get('id', '')} {lic_.get('label', '')}".strip(),
            extra={"credit": loc.get("credit")})


class Gutenberg(Adapter):
    name = "gutenberg"
    label = "Project Gutenberg (via the Gutendex API)"
    docs = "https://gutendex.com/"
    media = ("text",)

    def search(self, http: Http, q: Query) -> list[Item]:
        params = {"search": q.text, "author_year_start": q.year_from,
                  "author_year_end": q.year_to}
        data = http.json("https://gutendex.com/books/?" + qs(params))
        return self._rank([self.to_item(b) for b in data.get("results", [])[: q.limit]])

    def to_item(self, b: dict) -> Item:
        fmts = b.get("formats", {})
        txt = next((u for m, u in fmts.items() if m.startswith("text/plain")), None)
        authors = b.get("authors") or []
        death = authors[0].get("death_year") if authors else None
        return Item(
            source=self.name, id=str(b["id"]), title=b.get("title") or "", media_type="text",
            landing_url=f"https://www.gutenberg.org/ebooks/{b['id']}",
            creator=authors[0].get("name") if authors else None,
            date=str(death) if death else None, subjects=(b.get("subjects") or [])[:20],
            files=[MediaFile(url=txt, mime="text/plain")] if txt else [],
            thumb_url=fmts.get("image/jpeg"),
            rights_raw=("public domain in the USA (Project Gutenberg)" if b.get("copyright") is False
                        else "copyrighted or unknown (Project Gutenberg)"),
            extra={"date_is": "author death year"})


class Zenodo(Adapter):
    name = "zenodo"
    label = "Zenodo (datasets and corpora)"
    docs = "https://developers.zenodo.org/"
    media = ("dataset", "text", "model3d")

    def search(self, http: Http, q: Query) -> list[Item]:
        url = "https://zenodo.org/api/records?" + qs(
            {"q": q.text, "size": min(q.limit, 25), "type": "dataset"})
        return self._rank([self.to_item(r) for r in http.json(url).get("hits", {}).get("hits", [])])

    def to_item(self, r: dict) -> Item:
        md = r.get("metadata", {})
        lic_id = (md.get("license") or {}).get("id", "")
        return Item(
            source=self.name, id=str(r["id"]), title=md.get("title") or "", media_type="dataset",
            landing_url=r.get("links", {}).get("self_html") or f"https://zenodo.org/records/{r['id']}",
            creator=(md.get("creators") or [{}])[0].get("name"),
            date=md.get("publication_date"), description=md.get("description") or "",
            subjects=md.get("keywords") or [],
            files=[MediaFile(url=f["links"]["self"], size=f.get("size"), name=f.get("key"))
                   for f in (r.get("files") or [])[:3]],
            rights_raw=lic_id, extra={"doi": r.get("doi")})
