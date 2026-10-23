# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Zain Dana Harper
"""Derive lineage, rights reports and the clean-room gate with controls.

Controls: near-copies (recoloured, cropped, cropped+flipped, mirror-tiled,
pitched, excerpted) must fail; independent material in the same style must
pass; edits of public domain sources need no gate. Uses ffmpeg (slow spawn on
Windows, about a minute in total).
"""
import json
import random
import tempfile
import unittest
from pathlib import Path

from openarchives import cleanroom, derive
from openarchives import licence as lic
from openarchives import mediatools as mt
from openarchives.net import sha256_file
from openarchives.rights import AssetStore, basis_report, credits_markdown


def noise_image(out, seed):
    mt.run(["-f", "lavfi", "-i", "color=c=gray:s=640x480", "-vf",
            f"noise=all_seed={seed}:alls=100,gblur=sigma=10,eq=contrast=4", "-frames:v", "1", out])


def melody(out, seed, secs=24):
    rnd = random.Random(seed)
    notes = [rnd.choice([0, 2, 3, 5, 7, 8, 10, 12]) for _ in range(secs * 2)]
    f = "+".join(f"between(t,{i * 0.5},{i * 0.5 + 0.5})*{220 * 2 ** (n / 12):.2f}" for i, n in enumerate(notes))
    expr = f"0.5*sin(2*PI*({f})*t)+0.25*sin(4*PI*({f})*t)+0.12*sin(6*PI*({f})*t)"
    mt.run(["-f", "lavfi", "-i", f"aevalsrc='{expr}':s=22050:d={secs}", out])


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmpdir.name)
        cls.d = cls.root / "media"
        cls.d.mkdir()
        cls.store = AssetStore(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.tmpdir.cleanup()

    @classmethod
    def index(cls, path, key, licence_class):
        basis = lic.basis_for(licence_class)
        row = {"item": {"key": key, "title": key, "landing_url": f"https://example.org/{key}",
                        "licence": licence_class, "basis": basis,
                        "attribution": f'"{key}" via test. {licence_class}.'},
               "files": [{"path": str(path), "url": f"https://example.org/{key}.bin",
                          "sha256": sha256_file(Path(path)), "bytes": 1}]}
        with open(cls.root / "index.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")

    def p(self, name):
        return str(self.d / name)


class ImageGate(Base):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        for i, seed in enumerate((101, 202, 303), 1):
            noise_image(str(cls.d / f"n{i}.png"), seed)
        cls.index(cls.d / "n1.png", "test:ref-photo", lic.UNKNOWN)       # reference-only
        cls.index(cls.d / "n3.png", "test:pd-photo", lic.PD)

    def register_and_check(self, path):
        rec = self.store.register(path, [self.p("n1.png")], "control")
        return cleanroom.check_derived(self.store, rec["asset_id"])

    def test_near_copies_fail(self):
        controls = {
            "recolour.png": "format=rgb24,hue=h=140:s=3,eq=gamma=1.5:contrast=1.3",
            "crop.png": "crop=420:320:150:100,scale=640:480",
            "cropflip.png": "crop=300:300:200:120,scale=512:512,hflip",
        }
        for name, vf in controls.items():
            mt.run(["-i", self.p("n1.png"), "-vf", vf, self.p(name)])
            with self.subTest(control=name):
                gate = self.register_and_check(self.p(name))
                self.assertEqual(gate["verdict"], "fail", gate["results"])
        tile = derive.texture(self.store, self.p("n1.png"), self.p("tile.png"), 512,
                              region=(300, 200, 240, 240), preview=False)
        self.assertEqual(tile["basis"], lic.REFERENCE_ONLY)
        self.assertEqual(cleanroom.check_derived(self.store, tile["asset_id"])["verdict"], "fail")

    def test_independent_same_style_passes(self):
        gate = self.register_and_check(self.p("n2.png"))
        self.assertEqual(gate["verdict"], "pass", gate["results"])
        self.assertLess(gate["results"][0]["similarity"], cleanroom.IMAGE_FAIL)
        receipt = self.store.load(sha256_file(Path(self.p("n2.png")))[:16])
        self.assertEqual(receipt["clean_room"]["verdict"], "pass")

    def test_public_domain_edit_needs_no_gate_and_carries_lineage(self):
        rec = derive.texture(self.store, self.p("n3.png"), self.p("pd_tex.png"), 512)
        self.assertEqual(rec["basis"], lic.FREE)
        self.assertEqual(rec["inputs"][0]["item_key"], "test:pd-photo")
        self.assertEqual(rec["inputs"][0]["sha256"], sha256_file(Path(self.p("n3.png"))))
        self.assertTrue(Path(rec["preview"]).exists())
        w, h, _ = mt.decode_gray(self.p("pd_tex.png"), 512)
        self.assertEqual((w, h), (512, 512))
        self.assertEqual(cleanroom.check_derived(self.store, rec["asset_id"])["verdict"], "not-needed")
        report = basis_report(self.store)
        self.assertIn(rec["asset_id"], [r["asset_id"] for r in report["shippable_assets"][lic.FREE]])
        self.assertIn("test:pd-photo", credits_markdown(self.store))


class AudioGate(Base):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        melody(str(cls.d / "m1.wav"), 1)
        melody(str(cls.d / "m2.wav"), 2)
        cls.index(cls.d / "m1.wav", "test:ref-record", lic.NC)            # reference-only

    def test_pitched_and_excerpted_copies_fail(self):
        derive.pitch(self.store, self.p("m1.wav"), self.p("pitch2.wav"), 2.0, None)
        for name, args in {"pitch.wav": ["-ss", "5", "-i", self.p("pitch2.wav"), "-t", "10"],
                           "excerpt.wav": ["-ss", "8", "-i", self.p("m1.wav"), "-t", "8",
                                           "-af", "volume=4dB"]}.items():
            mt.run([*args, self.p(name)])
            with self.subTest(control=name):
                rec = self.store.register(self.p(name), [self.p("m1.wav")], "control")
                gate = cleanroom.check_derived(self.store, rec["asset_id"])
                self.assertEqual(gate["verdict"], "fail", gate["results"])

    def test_independent_melody_same_timbre_passes(self):
        rec = self.store.register(self.p("m2.wav"), [self.p("m1.wav")], "independent")
        gate = cleanroom.check_derived(self.store, rec["asset_id"])
        self.assertEqual(gate["verdict"], "pass", gate["results"])


class RightsRecords(Base):
    def test_fair_use_needs_reason_and_is_recorded(self):
        with self.assertRaises(ValueError):
            self.store.set_basis("loc:123", lic.FAIR_USE, "short")
        rec = self.store.set_basis("loc:123", lic.FAIR_USE,
                                   "Quoted for critique of 1940s poster rhetoric in explainer 3",
                                   use="explainer 3")
        self.assertEqual(self.store.overrides()["loc:123"]["basis"], lic.FAIR_USE)
        self.assertTrue(rec["date"])


if __name__ == "__main__":
    unittest.main()
