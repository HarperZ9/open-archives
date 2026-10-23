# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Zain Dana Harper
import unittest

from openarchives import licence as lic


class NormaliseTests(unittest.TestCase):
    CASES = [
        ("http://creativecommons.org/licenses/publicdomain/", lic.PD),          # IA Prelinger
        ("http://creativecommons.org/publicdomain/mark/1.0/", lic.PD),
        ("https://creativecommons.org/publicdomain/zero/1.0/", lic.CC0),
        ("CC0", lic.CC0),
        ("Public domain", lic.PD),                                              # Commons
        ("PD-US-expired", lic.PD),
        ("pdm Public Domain Mark", lic.PD),                                     # Wellcome
        ("CC BY 4.0", lic.CC_BY),
        ("https://creativecommons.org/licenses/by/2.0/", lic.CC_BY),
        ("by", lic.CC_BY),                                                      # Openverse
        ("CC BY-SA 3.0", lic.CC_BY_SA),
        ("cc-by-sa-4.0", lic.CC_BY_SA),
        ("http://creativecommons.org/licenses/by-nc-sa/4.0/", lic.NC),
        ("cc-by-nc 4.0", lic.NC),
        ("CC BY-ND 2.0", lic.ND),
        ("No known restrictions on publication.", lic.NKR),                    # LoC
        ("OFL-1.1", lic.OFL),
        ("MIT", lic.PERMISSIVE),
        ("Apache-2.0", lic.PERMISSIVE),
        ("GFDL", lic.OTHER_OPEN),
        ("http://rightsstatements.org/vocab/InC/1.0/", lic.IN_COPYRIGHT),
        ("All rights reserved", lic.IN_COPYRIGHT),
        ("", lic.UNKNOWN),
        ("see item record", lic.UNKNOWN),
    ]

    def test_cases(self):
        for text, expected in self.CASES:
            with self.subTest(text=text):
                self.assertEqual(lic.normalise(text), expected)

    def test_first_statement_wins(self):
        self.assertEqual(lic.normalise("https://creativecommons.org/licenses/by/4.0/",
                                       "public domain"), lic.CC_BY)
        self.assertEqual(lic.normalise(None, "", "CC0"), lic.CC0)

    def test_words_containing_pd_do_not_match(self):
        self.assertEqual(lic.normalise("updated-2020 notes"), lic.UNKNOWN)


class GateTests(unittest.TestCase):
    def test_basis_mapping(self):
        self.assertEqual(lic.basis_for(lic.PD), lic.FREE)
        self.assertEqual(lic.basis_for(lic.CC0), lic.FREE)
        self.assertEqual(lic.basis_for(lic.CC_BY), lic.CREDIT)
        self.assertEqual(lic.basis_for(lic.CC_BY_SA), lic.SHARE_ALIKE)
        for unclear in (lic.NC, lic.ND, lic.NKR, lic.UNKNOWN, lic.IN_COPYRIGHT, lic.OTHER_OPEN):
            self.assertEqual(lic.basis_for(unclear), lic.REFERENCE_ONLY, unclear)

    def test_derived_basis_takes_most_restrictive(self):
        self.assertEqual(lic.derived_basis([lic.FREE, lic.CREDIT]), lic.CREDIT)
        self.assertEqual(lic.derived_basis([lic.FREE, lic.SHARE_ALIKE, lic.CREDIT]), lic.SHARE_ALIKE)
        self.assertEqual(lic.derived_basis([lic.FREE, lic.REFERENCE_ONLY]), lic.REFERENCE_ONLY)
        self.assertEqual(lic.derived_basis([]), lic.REFERENCE_ONLY)

    def test_attribution_carries_tasl(self):
        text = lic.attribution("Mill", "A. Smith", "loc", lic.PD, None, "https://x/1")
        for part in ('"Mill"', "A. Smith", "loc", "https://x/1", "Public domain"):
            self.assertIn(part, text)


if __name__ == "__main__":
    unittest.main()
