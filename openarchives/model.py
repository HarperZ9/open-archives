# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Zain Dana Harper
"""The normalised search result shared by every adapter."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from . import licence as lic

MEDIA_TYPES = ("image", "video", "audio", "text", "texture", "font",
               "model3d", "dataset")


@dataclass
class MediaFile:
    url: str
    kind: str = "original"      # original, large, medium, thumb, derivative
    mime: str | None = None
    size: int | None = None     # bytes, when the source says
    name: str | None = None


@dataclass
class Item:
    source: str                 # adapter name
    id: str                     # source-local identifier
    title: str
    media_type: str             # one of MEDIA_TYPES
    landing_url: str            # human page for the item
    creator: str | None = None
    date: str | None = None     # source's own date text
    description: str = ""
    subjects: list[str] = field(default_factory=list)
    files: list[MediaFile] = field(default_factory=list)
    thumb_url: str | None = None
    licence_url: str | None = None
    rights_raw: str = ""        # the source's own rights words, kept verbatim
    licence: str = lic.UNKNOWN  # normalised class
    basis: str = lic.REFERENCE_ONLY
    attribution: str = ""
    score: float = 0.0
    rank: int = 0               # position in the source's own ranking
    extra: dict = field(default_factory=dict)

    def finalise(self) -> "Item":
        """Normalise licence, derive the basis and build attribution."""
        self.licence = lic.normalise(self.licence_url, self.rights_raw)
        self.basis = lic.basis_for(self.licence)
        if not self.attribution:
            self.attribution = lic.attribution(
                self.title, self.creator, self.source, self.licence,
                self.licence_url, self.landing_url)
        self.title = (self.title or self.id).strip()
        self.description = _clean(self.description)[:2000]
        return self

    @property
    def key(self) -> str:
        return f"{self.source}:{self.id}"

    @property
    def year(self) -> int | None:
        return parse_year(self.date)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["key"] = self.key
        d["year"] = self.year
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Item":
        d = {k: v for k, v in d.items() if k not in ("key", "year")}
        d["files"] = [MediaFile(**f) for f in d.get("files", [])]
        return cls(**d)


_YEAR = re.compile(r"(?<!\d)(1[0-9]{3}|20[0-9]{2})(?!\d)")


def parse_year(text: str | None) -> int | None:
    if not text:
        return None
    m = _YEAR.search(str(text))
    return int(m.group(1)) if m else None


def _clean(text) -> str:
    if isinstance(text, list):
        text = " ".join(str(t) for t in text)
    text = re.sub(r"<[^>]+>", " ", str(text or ""))
    return re.sub(r"\s+", " ", text).strip()


def first(value):
    """First element of a list, or the value itself."""
    if isinstance(value, list):
        return value[0] if value else None
    return value
