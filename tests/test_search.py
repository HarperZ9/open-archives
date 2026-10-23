# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Zain Dana Harper
import unittest

from openarchives import licence as lic
from openarchives import search as srch
from openarchives.model import Item


def item(title, source="s", rank=0, date=None, media="image", rights="", desc="", subjects=()):
    return Item(source=source, id=title, title=title, media_type=media,
                landing_url="https://x/" + title, date=date, rights_raw=rights,
                description=desc, subjects=list(subjects), rank=rank).finalise()


class RankTests(unittest.TestCase):
    def test_title_match_beats_description_match(self):
        a = item("Cotton mill at Bolton", rank=5)
        b = item("Street scene", rank=0, desc="a cotton mill appears far away in the haze")
        c = item("Portrait of a lady", rank=1)
        items = [c, b, a]
        srch.rank(items, "cotton mill")
        self.assertEqual([i.title for i in items][0], "Cotton mill at Bolton")
        self.assertEqual(items[-1].title, "Portrait of a lady")

    def test_source_rank_breaks_ties(self):
        a = item("mill", source="x", rank=3)
        b = item("mill ", source="y", rank=0)
        items = [a, b]
        srch.rank(items, "mill")
        self.assertEqual(items[0].source, "y")


class FilterTests(unittest.TestCase):
    def test_era(self):
        f = srch.Filters(year_from=1840, year_to=1955)
        self.assertTrue(srch.passes(item("a", date="ca. 1890"), f))
        self.assertFalse(srch.passes(item("b", date="1972"), f))
        self.assertTrue(srch.passes(item("c", date=None), f))
        f.strict_era = True
        self.assertFalse(srch.passes(item("c", date=None), f))

    def test_licence_and_basis(self):
        classes, bases = srch.parse_licence_filter("pd,cc0")
        f = srch.Filters(licences=classes)
        self.assertTrue(srch.passes(item("a", rights="public domain"), f))
        self.assertFalse(srch.passes(item("b", rights="CC BY 4.0"), f))
        classes, bases = srch.parse_licence_filter("shippable")
        f = srch.Filters(bases=bases)
        self.assertTrue(srch.passes(item("b", rights="CC BY 4.0"), f))
        self.assertFalse(srch.passes(item("c", rights="No known restrictions"), f))
        with self.assertRaises(ValueError):
            srch.parse_licence_filter("bogus")

    def test_media_texture_accepts_images(self):
        f = srch.Filters(media=("texture",))
        self.assertTrue(srch.passes(item("a", media="image"), f))
        self.assertFalse(srch.passes(item("b", media="audio"), f))

    def test_dedupe_internet_archive_presets(self):
        a = item("film", source="internet_archive", rank=4)
        b = item("film", source="ia_prelinger", rank=1)
        out = srch.dedupe([a, b])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].source, "ia_prelinger")


class RunTests(unittest.TestCase):
    def test_errors_are_reported_not_swallowed(self):
        from openarchives.adapters import Adapter, Query
        import openarchives.search as s

        class Boom(Adapter):
            name, media = "boom", ("image",)

            def search(self, http, q):
                raise RuntimeError("server down")

        class Fine(Adapter):
            name, media = "fine", ("image",)

            def search(self, http, q):
                return self._rank([item("mill one", source="fine")])

        saved = dict(s.BY_NAME)
        s.BY_NAME.update({"boom": Boom(), "fine": Fine()})
        try:
            rep = s.run(None, Query("mill", ("image",)), srch.Filters(), ["boom", "fine"])
        finally:
            s.BY_NAME.clear()
            s.BY_NAME.update(saved)
        self.assertIn("server down", rep.errors["boom"])
        self.assertEqual(len(rep.items), 1)
        self.assertEqual(rep.items[0].basis, lic.REFERENCE_ONLY)



class FilenameTests(unittest.TestCase):
    def test_long_names_keep_extension(self):
        from openarchives.library import safe_filename
        long = "William_Matthew_Hale_" + "x" * 200 + ".jpg"
        out = safe_filename(long, 120)
        self.assertTrue(out.endswith(".jpg"))
        self.assertLessEqual(len(out), 120)
        self.assertEqual(safe_filename("a b.tar"), "a_b.tar")


if __name__ == "__main__":
    unittest.main()
