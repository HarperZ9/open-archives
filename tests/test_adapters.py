# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Zain Dana Harper
"""Adapter parsing against real responses captured from each live API on 2026-10-23."""
import json
import unittest
from pathlib import Path

from openarchives import licence as lic
from openarchives.adapters import BY_NAME, Query
from openarchives.adapters.internet_archive import pick_files

FIX = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


class FakeHttp:
    """Returns canned JSON by URL substring; records the URLs asked for."""

    def __init__(self, routes):
        self.routes = routes
        self.urls = []

    def json(self, url, headers=None):
        self.urls.append(url)
        for key, data in self.routes.items():
            if key in url:
                return data
        raise AssertionError(f"unexpected URL {url}")


class AdapterParsing(unittest.TestCase):
    def check_common(self, items):
        self.assertTrue(items)
        for it in items:
            self.assertTrue(it.title and it.landing_url, it)
            self.assertIn(it.licence, lic.LICENCE_CLASSES)
            self.assertIn(it.basis, lic.BASES)
            self.assertTrue(it.attribution)

    def test_internet_archive_search_and_query(self):
        http = FakeHttp({"advancedsearch": load("ia_search.json")})
        q = Query("propaganda", ("video",), 1930, 1960, 3)
        items = BY_NAME["ia_prelinger"].search(http, q)
        self.check_common(items)
        self.assertIn("collection%3Aprelinger", http.urls[0])
        self.assertIn("year%3A%5B1930+TO+1960%5D", http.urls[0])
        self.assertEqual(items[0].media_type, "video")

    def test_internet_archive_picks_small_derivative(self):
        meta = load("ia_metadata.json")
        files = pick_files("DuckandC1951", meta["files"], "video")
        self.assertEqual(len(files), 1)
        self.assertTrue(files[0].url.startswith("https://archive.org/download/DuckandC1951/"))
        self.assertEqual(lic.normalise(meta["metadata"]["licenseurl"]), lic.PD)

    def test_wikimedia(self):
        items = BY_NAME["wikimedia_commons"].search(FakeHttp({"api.php": load("wikimedia.json")}),
                                                    Query("cotton mill", ("image",)))
        self.check_common(items)
        mill = next(i for i in items if "Cotton mill" in i.id)
        self.assertEqual(mill.licence, lic.PD)
        self.assertEqual(mill.basis, lic.FREE)
        self.assertEqual(mill.year, 1914)

    def test_loc_rights_advisory_is_not_a_licence(self):
        items = BY_NAME["loc"].search(FakeHttp({"loc.gov/photos": load("loc_photos.json")}),
                                      Query("cotton mill", ("image",)))
        self.check_common(items)
        self.assertEqual(items[0].licence, lic.NKR)
        self.assertEqual(items[0].basis, lic.REFERENCE_ONLY)
        self.assertTrue(items[0].files and "#" not in items[0].files[0].url)

    def test_museums_and_open_media(self):
        cases = [("cleveland", "clevelandart", "cleveland.json"),
                 ("artic", "artic.edu", "artic.json"),
                 ("nasa", "images-api", "nasa.json"),
                 ("openverse", "openverse", "openverse.json"),
                 ("wellcome", "wellcome", "wellcome.json"),
                 ("gutenberg", "gutendex", "gutendex.json")]
        for name, route, fixture in cases:
            with self.subTest(name=name):
                items = BY_NAME[name].search(FakeHttp({route: load(fixture)}),
                                             Query("mill", BY_NAME[name].media[:1], limit=5))
                self.check_common(items)

    def test_openverse_keeps_source_attribution(self):
        items = BY_NAME["openverse"].search(FakeHttp({"openverse": load("openverse.json")}),
                                            Query("mill town", ("image",)))
        self.assertIn("licensed under", items[0].attribution)
        self.assertEqual(items[0].licence, lic.CC_BY_SA)

    def test_keyed_adapters_unavailable_without_key(self):
        import os
        for name in ("smithsonian", "nypl", "europeana", "freesound", "bhl"):
            ad = BY_NAME[name]
            if not os.environ.get(ad.key_env):
                self.assertFalse(ad.available(), name)


if __name__ == "__main__":
    unittest.main()
