# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Zain Dana Harper
"""Adapter contract. One adapter per open API (or per preset of one)."""
from __future__ import annotations

import os
from dataclasses import dataclass

from ..model import Item
from ..net import Http


@dataclass
class Query:
    text: str
    media: tuple[str, ...] = ()          # empty means any
    year_from: int | None = None
    year_to: int | None = None
    limit: int = 20                      # per adapter

    def wants(self, media_type: str) -> bool:
        return not self.media or media_type in self.media


class Adapter:
    name = "base"
    label = "Base"
    docs = ""                 # current documentation URL the adapter follows
    docs_checked = "2026-10-23"
    media: tuple[str, ...] = ()
    key_env: str | None = None  # environment variable holding a key, if needed
    note = ""                 # status note shown by `sources`
    default = True            # included when no --sources is given

    def key(self) -> str | None:
        return os.environ.get(self.key_env) if self.key_env else None

    def available(self) -> bool:
        return self.key_env is None or bool(self.key())

    def supports(self, q: Query) -> bool:
        return not q.media or any(m in self.media for m in q.media)

    def search(self, http: Http, q: Query) -> list[Item]:
        raise NotImplementedError

    def resolve(self, http: Http, item: Item) -> Item:
        """Fill in downloadable files when search results lack them."""
        return item

    def _rank(self, items: list[Item]) -> list[Item]:
        for i, it in enumerate(items):
            it.rank = i
            it.finalise()
        return items
