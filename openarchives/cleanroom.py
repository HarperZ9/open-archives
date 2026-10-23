# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Zain Dana Harper
"""The clean-room gate: an asset made with reference-only material in view must
not reproduce that material's expression.

check_derived compares the asset with every reference-only source in its
lineage (inputs and references, followed through earlier derived assets).
Public domain and CC0 sources need no gate, and neither do CC BY or CC BY-SA
sources, whose licences already permit derivatives with credit. The verdict is
written into the asset's receipt.

Calibration on synthetic controls (2026-10-23): pitched or excerpted copies
of melodies and ambience scored 0.76 to 0.99; independent melodies in the same
timbre and independent ambience scored 0.52 to 0.57. Images: recoloured,
cropped, flipped and mirror-tiled copies 0.94 to 0.99; independent textures of
the same kind 0.70 to 0.75. Real material is checked in the proof run.

Thresholds were set from controls (see tests/test_cleanroom.py and the proof
run): near-copies (recoloured, cropped, mirrored, pitched) score above them and
independently made material in the same style scores below.
"""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from . import licence as lic
from . import mediatools as mt
from . import audioprint as ap
from . import perceptual as pc
from .rights import AssetStore, now

log = logging.getLogger("openarchives.cleanroom")

IMAGE_FAIL = 0.85
AUDIO_FAIL = 0.66
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp", ".bmp", ".gif", ".jp2"}
AUDIO_EXT = {".mp3", ".wav", ".flac", ".ogg", ".oga", ".m4a", ".aac", ".opus"}
VIDEO_EXT = {".mp4", ".mkv", ".webm", ".ogv", ".mov", ".avi", ".mpeg", ".mpg"}
# Bases whose terms already permit reuse (fair use is a recorded, deliberate
# quotation for commentary, so it is not a clean-room question either).
GATE_FREE = {lic.FREE, lic.OWN_WORK, lic.CREDIT, lic.SHARE_ALIKE, lic.LICENSED, lic.FAIR_USE}


def kind_of(path: str) -> str:
    ext = Path(path).suffix.lower()
    if ext in IMAGE_EXT:
        return "image"
    if ext in AUDIO_EXT:
        return "audio"
    if ext in VIDEO_EXT:
        return "video"
    return "other"


def gated_sources(store: AssetStore, rec: dict, depth: int = 0) -> list[dict]:
    """Reference-only (or unknown) sources anywhere in the lineage."""
    out = []
    for src in rec.get("inputs", []) + rec.get("references", []):
        if "asset_id" in src and depth < 5:
            try:
                out += gated_sources(store, store.load(src["asset_id"]), depth + 1)
            except KeyError:
                log.error("lineage points at missing asset %s", src["asset_id"])
                out.append(src)
            continue
        if src.get("basis") not in GATE_FREE:
            out.append(src)
    return out


def _frames(video: str, n: int, tmp: Path, tag: str) -> list[str]:
    dur = mt.duration(video) or 1.0
    frames = []
    for i in range(n):
        f = tmp / f"{tag}_{i}.png"
        mt.run(["-ss", f"{dur * (0.1 + 0.8 * i / max(n - 1, 1)):.2f}", "-i", video,
                "-frames:v", "1", str(f)])
        frames.append(str(f))
    return frames


def compare(asset_path: str, source_path: str) -> dict:
    ak, sk = kind_of(asset_path), kind_of(source_path)
    if ak == "audio" or (ak == "video" and sk == "audio"):
        if sk not in ("audio", "video"):
            return {"method": "none", "similarity": 0.0, "note": f"cannot compare {ak} with {sk}"}
        r = ap.audio_similarity(asset_path, source_path)
        r["envelope"]["note"] = ("informational only: periodic envelopes are a style trait, "
                                 "so this does not decide the verdict")
        return {"method": "audio-fingerprint", "threshold": AUDIO_FAIL, **r}
    if ak in ("image", "video") and sk in ("image", "video"):
        with tempfile.TemporaryDirectory() as tmp:
            a_imgs = _frames(asset_path, 5, Path(tmp), "a") if ak == "video" else [asset_path]
            s_imgs = _frames(source_path, 5, Path(tmp), "s") if sk == "video" else [source_path]
            best = {"similarity": 0.0, "match": None}
            for a in a_imgs:
                for s in s_imgs:
                    r = pc.image_similarity(a, s)
                    if r["similarity"] > best["similarity"]:
                        best = r
        return {"method": "phash+dhash crop-and-tile", "threshold": IMAGE_FAIL, **best}
    return {"method": "none", "similarity": 0.0, "note": f"no comparator for {ak} vs {sk}"}


def check_derived(store: AssetStore, asset: str) -> dict:
    rec = store.load(asset)
    sources = gated_sources(store, rec)
    results = []
    for src in sources:
        path = src.get("path")
        if not path or not Path(path).exists():
            results.append({"source": src.get("item_key") or path, "pass": False,
                            "note": "source file missing; cannot clear"})
            continue
        r = compare(rec["path"], path)
        threshold = r.get("threshold", 1.0)
        ok = r["method"] != "none" and r["similarity"] < threshold
        if r["method"] == "none":
            r["note"] = r.get("note", "") + "; unverifiable, held for human review"
        results.append({"source": src.get("item_key") or path, "source_basis": src.get("basis"),
                        "pass": ok, **r})
    verdict = "not-needed" if not sources else ("pass" if all(x["pass"] for x in results) else "fail")
    rec["clean_room"] = {"checked": now(), "verdict": verdict,
                         "thresholds": {"image": IMAGE_FAIL, "audio": AUDIO_FAIL},
                         "rule": "fail when similarity to any reference-only source >= threshold",
                         "results": results}
    store.save(rec)
    return rec["clean_room"]
