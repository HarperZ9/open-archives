# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Zain Dana Harper
"""Adapters that need a key or are blocked for scripted clients.

These follow each API's current documentation but stay inactive until the
user supplies a key in the named environment variable. No account was
created by this tool. Smithsonian works with the api.data.gov DEMO_KEY for a
low-volume trial; set SI_API_KEY=DEMO_KEY to use that.
"""
from __future__ import annotations

from ..model import Item, MediaFile, first
from ..net import Http, qs
from .base import Adapter, Query


class Smithsonian(Adapter):
    name = "smithsonian"
    label = "Smithsonian Open Access"
    docs = "https://edan.si.edu/openaccess/apidocs/"
    media = ("image", "texture", "model3d")
    key_env = "SI_API_KEY"
    note = "Needs an api.data.gov key (free sign-up)."

    def search(self, http: Http, q: Query) -> list[Item]:
        url = "https://api.si.edu/openaccess/api/v1.0/search?" + qs({
            "q": f"({q.text}) AND online_media_type:Images", "rows": min(q.limit, 100),
            "api_key": self.key()})
        rows = http.json(url).get("response", {}).get("rows", [])
        return self._rank([i for i in (self.to_item(r) for r in rows) if i])

    def to_item(self, r: dict) -> Item | None:
        dnr = r.get("content", {}).get("descriptiveNonRepeating", {})
        media = (dnr.get("online_media") or {}).get("media") or []
        img = next((m for m in media if m.get("type") == "Images"), None)
        if not img:
            return None
        ist = r.get("content", {}).get("indexedStructured", {})
        names = r.get("content", {}).get("freetext", {}).get("name") or []
        access = (img.get("usage") or {}).get("access", "")
        return Item(
            source=self.name, id=r["id"], title=r.get("title") or "", media_type="image",
            landing_url=dnr.get("record_link") or r.get("url", ""),
            creator=names[0].get("content") if names else None,
            date=str(first(ist.get("date")) or ""), subjects=ist.get("topic") or [],
            files=[MediaFile(url=img.get("content"))], thumb_url=img.get("thumbnail"),
            rights_raw=access or "usage not stated", extra={"unit": dnr.get("unit_code")})


class Nypl(Adapter):
    name = "nypl"
    label = "NYPL Digital Collections"
    docs = "https://api.repo.nypl.org/"
    media = ("image", "texture")
    key_env = "NYPL_API_TOKEN"
    note = "Needs a free API token (sign-up required). Unverified live."

    def search(self, http: Http, q: Query) -> list[Item]:
        url = "https://api.repo.nypl.org/api/v2/items/search?" + qs(
            {"q": q.text, "publicDomainOnly": "true", "per_page": min(q.limit, 50)})
        data = http.json(url, {"Authorization": f'Token token="{self.key()}"'})
        res = data.get("nyplAPI", {}).get("response", {}).get("result", [])
        return self._rank([Item(
            source=self.name, id=r.get("uuid", ""), title=r.get("title") or "", media_type="image",
            landing_url=r.get("itemLink", ""),
            thumb_url=f"https://images.nypl.org/index.php?id={r.get('imageID')}&t=w",
            files=[MediaFile(url=f"https://images.nypl.org/index.php?id={r.get('imageID')}&t=g")],
            rights_raw="public domain (NYPL publicDomainOnly filter)") for r in res])


_EUROPEANA_MEDIA = {"IMAGE": "image", "VIDEO": "video", "SOUND": "audio", "TEXT": "text", "3D": "model3d"}


class Europeana(Adapter):
    name = "europeana"
    label = "Europeana"
    docs = "https://europeana.atlassian.net/wiki/spaces/EF/pages/2385739812/Search+API+Documentation"
    media = ("image", "texture", "video", "audio", "text", "model3d")
    key_env = "EUROPEANA_API_KEY"
    note = "Needs a free wskey (sign-up required)."

    def search(self, http: Http, q: Query) -> list[Item]:
        url = "https://api.europeana.eu/record/v2/search.json?" + qs({
            "wskey": self.key(), "query": q.text, "rows": min(q.limit, 100),
            "media": "true", "reusability": "open"})
        return self._rank([self.to_item(r) for r in http.json(url).get("items", [])])

    def to_item(self, r: dict) -> Item:
        shown = first(r.get("edmIsShownBy"))
        return Item(
            source=self.name, id=r.get("id", ""), title=str(first(r.get("title")) or ""),
            media_type=_EUROPEANA_MEDIA.get(r.get("type", ""), "image"),
            landing_url=r.get("guid", ""), creator=first(r.get("dcCreator")),
            date=str(first(r.get("year")) or ""), files=[MediaFile(url=shown)] if shown else [],
            thumb_url=first(r.get("edmPreview")), licence_url=first(r.get("rights")),
            extra={"provider": first(r.get("dataProvider"))})


class Freesound(Adapter):
    name = "freesound"
    label = "Freesound"
    docs = "https://freesound.org/docs/api/"
    media = ("audio",)
    key_env = "FREESOUND_API_KEY"
    note = ("Needs an API token (sign-up required). Many CC Freesound sounds "
            "are already reachable keyless through Openverse audio.")

    def search(self, http: Http, q: Query) -> list[Item]:
        url = "https://freesound.org/apiv2/search/text/?" + qs({
            "query": q.text, "page_size": min(q.limit, 150), "token": self.key(),
            "fields": "id,name,license,username,previews,url,tags,duration,created"})
        return self._rank([Item(
            source=self.name, id=str(r["id"]), title=r.get("name") or "", media_type="audio",
            landing_url=r.get("url", ""), creator=r.get("username"), date=r.get("created"),
            subjects=r.get("tags") or [],
            files=[MediaFile(url=(r.get("previews") or {}).get("preview-hq-mp3", ""), kind="preview")],
            licence_url=r.get("license")) for r in http.json(url).get("results", [])])


class Bhl(Adapter):
    name = "bhl"
    label = "Biodiversity Heritage Library"
    docs = "https://www.biodiversitylibrary.org/docs/api3.html"
    media = ("text", "image")
    key_env = "BHL_API_KEY"
    note = "Needs a free API key (sign-up required). Unverified live."

    def search(self, http: Http, q: Query) -> list[Item]:
        url = "https://www.biodiversitylibrary.org/api3?" + qs({
            "op": "PublicationSearch", "searchterm": q.text, "searchtype": "F",
            "format": "json", "apikey": self.key()})
        res = http.json(url).get("Result") or []
        return self._rank([Item(
            source=self.name, id=str(r.get("ItemID") or r.get("TitleID") or ""),
            title=r.get("Title") or "", media_type="text",
            landing_url=r.get("ItemUrl") or r.get("TitleUrl") or "",
            date=str(r.get("PublicationDate") or r.get("Year") or ""),
            rights_raw=r.get("Rights") or r.get("LicenseUrl") or "") for r in res[: q.limit]])


class ScienceMuseumGroup(Adapter):
    name = "sciencemuseum"
    label = "Science Museum Group collection"
    docs = "https://github.com/TheScienceMuseum/collections-online/wiki/Collections-Online-API"
    media = ("image",)
    default = False
    note = ("Blocked: the CloudFront bot filter returns 403 to scripted clients "
            "(checked 2026-10-23). Not worked around.")

    def search(self, http: Http, q: Query) -> list[Item]:
        data = http.json("https://collection.sciencemuseumgroup.org.uk/search?" + qs({"q": q.text}),
                         {"Accept": "application/json"})
        return self._rank([Item(
            source=self.name, id=d.get("id", ""),
            title=str(first((d.get("attributes") or {}).get("summary_title")) or ""),
            media_type="image", landing_url=(d.get("links") or {}).get("self", ""))
            for d in data.get("data", [])])
