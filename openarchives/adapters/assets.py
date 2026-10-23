# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Zain Dana Harper
"""Production asset sources: Poly Haven (CC0 textures, HDRIs, 3D models) and
Fontsource (open-licensed fonts).

Poly Haven: https://api.polyhaven.com/ (docs linked from the API root; CC0 assets).
Fontsource: https://fontsource.org/docs/api (keyless; licence per family).
Neither API has full-text search, so the catalogue is fetched once per run and
matched locally against the query words.
"""
from __future__ import annotations

import re

from ..model import Item, MediaFile
from ..net import Http
from .base import Adapter, Query

_WORD = re.compile(r"[a-z0-9]+")


def _words(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


def _match(query: str, haystack: str) -> float:
    q = _words(query)
    if not q:
        return 0.0
    hay = _words(haystack)
    # Count a hit for plural or prefix forms too (brick/bricks).
    hits = sum(1 for w in q if w in hay or any(h.startswith(w) or w.startswith(h)
                                                for h in hay if len(h) > 3))
    return hits / len(q)


class PolyHaven(Adapter):
    name = "polyhaven"
    label = "Poly Haven (CC0 textures, HDRIs, 3D models)"
    docs = "https://api.polyhaven.com/"
    media = ("texture", "model3d", "image")
    resolution = "2k"
    _cache: dict[str, dict] = {}

    def _catalogue(self, http: Http, kind: str) -> dict:
        if kind not in self._cache:
            self._cache[kind] = http.json(f"https://api.polyhaven.com/assets?t={kind}")
        return self._cache[kind]

    def search(self, http: Http, q: Query) -> list[Item]:
        kinds = []
        if q.wants("texture") or q.wants("image"):
            kinds += ["textures", "hdris"]
        if q.wants("model3d"):
            kinds.append("models")
        scored = []
        for kind in kinds:
            for aid, a in self._catalogue(http, kind).items():
                hay = " ".join([aid, a.get("name", ""), *a.get("tags", []), *a.get("categories", [])])
                s = _match(q.text, hay)
                if s >= 0.5:
                    scored.append((s, a.get("download_count", 0), aid, a, kind))
        scored.sort(key=lambda t: (-t[0], -t[1]))
        return self._rank([self.to_item(aid, a, kind) for _, _, aid, a, kind in scored[: q.limit]])

    def to_item(self, aid: str, a: dict, kind: str) -> Item:
        mtype = "model3d" if kind == "models" else "texture"
        return Item(
            source=self.name, id=aid, title=a.get("name") or aid, media_type=mtype,
            landing_url=f"https://polyhaven.com/a/{aid}",
            creator=", ".join(a.get("authors", {}).keys()) or None,
            date=None, subjects=[*a.get("tags", []), *a.get("categories", [])],
            thumb_url=f"https://cdn.polyhaven.com/asset_img/thumbs/{aid}.png?width=400",
            licence_url="https://creativecommons.org/publicdomain/zero/1.0/",
            rights_raw="CC0 (Poly Haven)", extra={"kind": kind})

    def resolve(self, http: Http, item: Item) -> Item:
        files = http.json(f"https://api.polyhaven.com/files/{item.id}")
        res = self.resolution
        out: list[MediaFile] = []
        if item.extra.get("kind") == "hdris":
            hdr = files.get("hdri", {}).get("1k", {}).get("hdr")
            out = [MediaFile(url=hdr["url"], size=hdr.get("size"))] if hdr else []
        elif item.extra.get("kind") == "models":
            gl = files.get("gltf", {}).get("1k", {}).get("gltf")
            if gl:
                out = [MediaFile(url=gl["url"], size=gl.get("size"))]
                out += [MediaFile(url=v["url"], size=v.get("size"))
                        for v in gl.get("include", {}).values()]
        else:
            for mapname in ("Diffuse", "nor_gl", "Rough", "Displacement"):
                f = files.get(mapname, {}).get(res, {}).get("jpg") or \
                    files.get(mapname, {}).get(res, {}).get("png")
                if f:
                    out.append(MediaFile(url=f["url"], size=f.get("size"), kind=mapname))
        item.files = out
        return item


class Fontsource(Adapter):
    name = "fontsource"
    label = "Fontsource (open-licensed fonts)"
    docs = "https://fontsource.org/docs/api/fonts"
    media = ("font",)
    _cache: list = []

    def search(self, http: Http, q: Query) -> list[Item]:
        if not Fontsource._cache:
            Fontsource._cache = http.json("https://api.fontsource.org/v1/fonts")
        scored = []
        for f in Fontsource._cache:
            s = _match(q.text, " ".join([f.get("family", ""), f.get("category", ""), f.get("id", "")]))
            if s >= 0.5:
                scored.append((s, f))
        scored.sort(key=lambda t: -t[0])
        return self._rank([self.to_item(f) for _, f in scored[: q.limit]])

    def to_item(self, f: dict) -> Item:
        return Item(
            source=self.name, id=f["id"], title=f.get("family") or f["id"], media_type="font",
            landing_url=f"https://fontsource.org/fonts/{f['id']}", date=f.get("lastModified"),
            subjects=[f.get("category", ""), f.get("type", "")],
            rights_raw=f.get("license", ""),
            extra={"note": "date is the package's last modification, not the design date"})

    def resolve(self, http: Http, item: Item) -> Item:
        d = http.json(f"https://api.fontsource.org/v1/fonts/{item.id}")
        variants = d.get("variants", {})
        weight = "400" if "400" in variants else next(iter(variants), None)
        style = variants.get(weight, {}).get("normal") or next(iter(variants.get(weight, {}).values()), {})
        sub = style.get(d.get("defSubset", "latin")) or next(iter(style.values()), {})
        url = (sub.get("url") or {}).get("ttf") or (sub.get("url") or {}).get("woff2")
        item.files = [MediaFile(url=url, name=f"{item.id}-{weight}.ttf")] if url else []
        item.extra["licence_detail"] = d.get("license")
        return item
