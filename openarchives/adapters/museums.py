# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Zain Dana Harper
"""Museum open access APIs: the Met, Art Institute of Chicago, Cleveland, Rijksmuseum.

Met: https://metmuseum.github.io/ (v1 search retired 2026-10-01, per the live
API's own 410 message; v1.1 search is paginated, objects stay on v1).
AIC: https://api.artic.edu/docs/   Cleveland: https://openaccess-api.clevelandart.org/
Rijksmuseum: https://data.rijksmuseum.nl/docs/search (Linked Art, keyless).
"""
from __future__ import annotations

from ..model import Item, MediaFile
import logging

from ..net import Http, HttpError, qs
from .base import Adapter, Query

log = logging.getLogger("openarchives.museums")
MET = "https://collectionapi.metmuseum.org/public/collection"


class Met(Adapter):
    name = "met"
    label = "The Metropolitan Museum of Art Open Access"
    docs = "https://metmuseum.github.io/"
    media = ("image", "texture")
    max_objects = 12

    def search(self, http: Http, q: Query) -> list[Item]:
        url = f"{MET}/v1.1/search?" + qs({"q": q.text, "hasImages": "true",
                                           "limit": min(q.limit, self.max_objects),
                                           "offset": 0})
        ids = http.json(url).get("objectIDs") or []
        items = []
        for oid in ids[: min(q.limit, self.max_objects)]:
            try:
                obj = http.json(f"{MET}/v1/objects/{oid}")
            except HttpError as exc:   # search can list withdrawn objects
                log.warning("Met object %s skipped: %s", oid, exc)
                continue
            if obj.get("primaryImage") or obj.get("primaryImageSmall"):
                items.append(self.to_item(obj))
        return self._rank(items)

    def to_item(self, o: dict) -> Item:
        pd = bool(o.get("isPublicDomain"))
        files = [MediaFile(url=o["primaryImage"], kind="original")] if pd and o.get("primaryImage") else []
        return Item(
            source=self.name, id=str(o["objectID"]), title=o.get("title") or "",
            media_type="image", landing_url=o.get("objectURL", ""),
            creator=o.get("artistDisplayName") or o.get("culture") or None,
            date=o.get("objectDate") or str(o.get("objectBeginDate") or ""),
            description=" ".join(filter(None, [o.get("medium"), o.get("classification")])),
            subjects=[t["term"] for t in (o.get("tags") or []) if t.get("term")],
            files=files, thumb_url=o.get("primaryImageSmall"),
            licence_url="https://creativecommons.org/publicdomain/zero/1.0/" if pd else None,
            rights_raw="Met Open Access (CC0)" if pd else "Not in Met Open Access; in copyright or restricted")


class ArtInstituteChicago(Adapter):
    name = "artic"
    label = "Art Institute of Chicago"
    docs = "https://api.artic.edu/docs/"
    media = ("image", "texture")
    # AIC docs: request /full/843,/0/default.jpg and send AIC-User-Agent (see net.py).
    fields = "id,title,is_public_domain,image_id,date_display,date_start,artist_display,medium_display,term_titles"

    def search(self, http: Http, q: Query) -> list[Item]:
        url = "https://api.artic.edu/api/v1/artworks/search?" + qs(
            {"q": q.text, "limit": min(q.limit, 50), "fields": self.fields})
        data = http.json(url)
        iiif = data.get("config", {}).get("iiif_url", "https://www.artic.edu/iiif/2")
        return self._rank([self.to_item(d, iiif) for d in data.get("data", []) if d.get("image_id")])

    def to_item(self, d: dict, iiif: str) -> Item:
        pd = bool(d.get("is_public_domain"))
        img = f"{iiif}/{d['image_id']}/full/843,/0/default.jpg"
        return Item(
            source=self.name, id=str(d["id"]), title=d.get("title") or "",
            media_type="image", landing_url=f"https://www.artic.edu/artworks/{d['id']}",
            creator=(d.get("artist_display") or "").split("\n")[0] or None,
            date=d.get("date_display") or str(d.get("date_start") or ""),
            description=d.get("medium_display") or "", subjects=d.get("term_titles") or [],
            files=[MediaFile(url=img, kind="large")] if pd else [],
            thumb_url=f"{iiif}/{d['image_id']}/full/400,/0/default.jpg",
            licence_url="https://creativecommons.org/publicdomain/zero/1.0/" if pd else None,
            rights_raw="AIC public domain (CC0)" if pd else "In copyright or rights unclear")


class Cleveland(Adapter):
    name = "cleveland"
    label = "Cleveland Museum of Art Open Access"
    docs = "https://openaccess-api.clevelandart.org/"
    media = ("image", "texture")

    def search(self, http: Http, q: Query) -> list[Item]:
        params = {"q": q.text, "limit": min(q.limit, 50), "has_image": 1,
                  "created_after": q.year_from, "created_before": q.year_to}
        data = http.json("https://openaccess-api.clevelandart.org/api/artworks/?" + qs(params))
        return self._rank([self.to_item(d) for d in data.get("data", [])])

    def to_item(self, d: dict) -> Item:
        imgs = d.get("images") or {}
        best = (imgs.get("print") or imgs.get("web") or {}).get("url")
        creators = d.get("creators") or []
        return Item(
            source=self.name, id=str(d["id"]), title=d.get("title") or "",
            media_type="image", landing_url=d.get("url", ""),
            creator=creators[0].get("description") if creators else None,
            date=d.get("creation_date"), description=d.get("description") or "",
            subjects=[d.get("type") or "", d.get("technique") or ""],
            files=[MediaFile(url=best, kind="large")] if best else [],
            thumb_url=(imgs.get("web") or {}).get("url"),
            rights_raw=d.get("share_license_status") or "")


RIJKS = "https://data.rijksmuseum.nl/search/collection"
LD = {"Accept": "application/ld+json"}


class Rijksmuseum(Adapter):
    name = "rijksmuseum"
    label = "Rijksmuseum (Linked Art search, keyless)"
    docs = "https://data.rijksmuseum.nl/docs/search"
    media = ("image", "texture")
    max_objects = 6
    note = "Each object resolves through three Linked Art records, so results are capped at 6."

    def search(self, http: Http, q: Query) -> list[Item]:
        ids: list[str] = []
        for field in ("description", "title"):
            data = http.json(f"{RIJKS}?" + qs({field: q.text, "imageAvailable": "true"}))
            ids += [o["id"] for o in data.get("orderedItems", []) if o["id"] not in ids]
            if len(ids) >= self.max_objects:
                break
        items = []
        for oid in ids[: min(q.limit, self.max_objects)]:
            try:
                items.append(self.resolve_object(http, oid))
            except HttpError as exc:
                log.warning("Rijksmuseum object %s skipped: %s", oid, exc)
        return self._rank([i for i in items if i])

    def resolve_object(self, http: Http, oid: str) -> Item | None:
        obj = http.json(oid, LD)
        english = "http://vocab.getty.edu/aat/300388277"
        name_recs = [n for n in obj.get("identified_by", []) if n.get("type") == "Name"]
        name_recs.sort(key=lambda n: not any(l.get("id") == english for l in n.get("language", [])))
        names = [n.get("content") for n in name_recs]
        number = next((n.get("content") for n in obj.get("identified_by", [])
                       if n.get("type") == "Identifier"), oid.split("/")[-1])
        span = (obj.get("produced_by") or {}).get("timespan") or {}
        date = next((n.get("content") for n in span.get("identified_by", [])), None) \
            or (span.get("begin_of_the_begin") or "")[:4]
        img, rights, rights_url = None, "", None
        for vis in obj.get("shows", [])[:1]:
            vrec = http.json(vis["id"], LD)
            for right in vrec.get("subject_to", []):
                for c in right.get("classified_as", []):
                    rights_url, rights = c.get("id"), c.get("_label", "")
            for dig in vrec.get("digitally_shown_by", [])[:1]:
                drec = http.json(dig["id"], LD)
                img = next((a["id"] for a in drec.get("access_point", [])), None)
        if not img:
            return None
        title = names[0] if names else number
        return Item(
            source=self.name, id=str(number), title=title, media_type="image",
            landing_url=f"https://www.rijksmuseum.nl/en/collection/{number}",
            date=date, files=[MediaFile(url=img, kind="original")],
            thumb_url=img.replace("/full/max/", "/full/400,/"),
            licence_url=rights_url, rights_raw=rights, extra={"lod": oid})
