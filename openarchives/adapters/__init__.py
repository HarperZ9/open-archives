# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Zain Dana Harper
"""Adapter registry."""
from __future__ import annotations

from .assets import Fontsource, PolyHaven
from .base import Adapter, Query
from .internet_archive import Etree, InternetArchive, Musopen, Prelinger, SeventyEight
from .keyed import Bhl, Europeana, Freesound, Nypl, ScienceMuseumGroup, Smithsonian
from .museums import ArtInstituteChicago, Cleveland, Met, Rijksmuseum
from .open_media import Gutenberg, Nasa, Openverse, Wellcome, Zenodo
from .wikimedia_loc import LibraryOfCongress, WikimediaCommons

ALL: list[Adapter] = [
    InternetArchive(), Prelinger(), SeventyEight(), Etree(), Musopen(),
    WikimediaCommons(), LibraryOfCongress(), Smithsonian(), Met(), Rijksmuseum(),
    Nypl(), Europeana(), Nasa(), Openverse(), Freesound(), Gutenberg(), Bhl(),
    ArtInstituteChicago(), Cleveland(), Wellcome(), PolyHaven(), Fontsource(),
    Zenodo(), ScienceMuseumGroup(),
]
BY_NAME = {a.name: a for a in ALL}

__all__ = ["ALL", "BY_NAME", "Adapter", "Query"]
