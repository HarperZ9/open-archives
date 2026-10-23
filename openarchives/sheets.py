# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Zain Dana Harper
"""Contact sheets for fast review: video frames, image grids, audio waveforms.

Every sheet is written with a JSON sidecar mapping each cell to its item,
licence and rights basis, so a reviewer can go from a cell to its receipt.
"""
from __future__ import annotations

import json
import logging
import math
import tempfile
from pathlib import Path

from . import mediatools as mt
from .model import Item
from .net import Http

log = logging.getLogger("openarchives.sheets")
BG = "0x1b1b1b"


def _labelled(vf: str, label: str | None) -> list[str]:
    """Return filter variants: with a label first, then without (fallback)."""
    return [f"{vf},{mt.label_filter(label)}", vf] if label else [vf]


def _render_cell(src: str, out: Path, w: int, h: int, label: str | None,
                 seek: float | None = None) -> bool:
    vf = (f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
          f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color={BG},format=rgb24")
    pre = ["-ss", f"{seek:.2f}"] if seek is not None else []
    for variant in _labelled(vf, label):
        try:
            mt.run([*pre, "-i", src, "-frames:v", "1", "-vf", variant, str(out)], timeout=180)
            return True
        except mt.FfmpegError as exc:
            log.warning("cell render failed for %s: %s", src, str(exc)[:200])
    return False


def _tile(cells_dir: Path, count: int, cols: int, out: Path) -> Path:
    rows = max(1, math.ceil(count / cols))
    mt.run(["-framerate", "1", "-i", str(cells_dir / "cell_%03d.png"), "-vf",
            f"tile={cols}x{rows}:padding=6:margin=6:color={BG}", "-frames:v", "1",
            "-q:v", "3", str(out)])
    return out


def video_sheet(src: str, out: Path, cols: int = 4, rows: int = 3, width: int = 320) -> Path:
    """Frames at even intervals from a local file or a URL (ffmpeg seeks by range)."""
    dur = mt.duration(src)
    if not dur:
        raise mt.FfmpegError(f"could not read duration of {src}")
    n = cols * rows
    height = width * 3 // 4
    with tempfile.TemporaryDirectory() as tmp:
        tmpd = Path(tmp)
        k = 0
        for i in range(n):
            t = dur * (0.03 + 0.94 * i / max(n - 1, 1))
            label = f"{int(t // 60):02d}:{int(t % 60):02d}"
            if _render_cell(src, tmpd / f"cell_{k:03d}.png", width, height, label, seek=t):
                k += 1
        if not k:
            raise mt.FfmpegError(f"no frames extracted from {src}")
        out.parent.mkdir(parents=True, exist_ok=True)
        return _tile(tmpd, k, cols, out)


def image_grid(entries: list[tuple[str, str]], out: Path, cols: int = 6, cell: int = 300) -> Path:
    """entries: (local path or URL, label). Unreadable images are skipped."""
    with tempfile.TemporaryDirectory() as tmp:
        tmpd = Path(tmp)
        k = 0
        for src, label in entries:
            if _render_cell(src, tmpd / f"cell_{k:03d}.png", cell, cell, label):
                k += 1
        if not k:
            raise mt.FfmpegError("no images could be rendered")
        out.parent.mkdir(parents=True, exist_ok=True)
        return _tile(tmpd, k, cols, out)


def audio_sheet(entries: list[tuple[str, str]], out: Path, width: int = 900) -> Path:
    """One waveform strip per track, stacked."""
    with tempfile.TemporaryDirectory() as tmp:
        tmpd = Path(tmp)
        k = 0
        for src, label in entries:
            vf = f"dynaudnorm,showwavespic=s={width}x110:scale=sqrt:colors=0xd8d8d8,{mt.label_filter(label)}"
            try:
                mt.run(["-t", "240", "-i", src, "-filter_complex", vf, "-frames:v", "1",
                        str(tmpd / f"cell_{k:03d}.png")], timeout=240)
                k += 1
            except mt.FfmpegError as exc:
                log.warning("waveform failed for %s: %s", src, str(exc)[:200])
        if not k:
            raise mt.FfmpegError("no waveforms rendered")
        out.parent.mkdir(parents=True, exist_ok=True)
        return _tile(tmpd, k, 1, out)


def thumbs_for(http: Http, items: list[Item], workdir: Path) -> list[tuple[str, str]]:
    """Download each item's thumbnail (polite client) and return grid entries."""
    entries = []
    for n, it in enumerate(items, 1):
        if not it.thumb_url:
            continue
        dest = workdir / f"thumb_{n:03d}.img"
        try:
            http.download(it.thumb_url, dest, 8 << 20)
            entries.append((str(dest), f"{n} {it.basis[:3]} {it.licence}"))
        except Exception as exc:
            log.warning("thumbnail failed for %s: %s", it.key, exc)
    return entries


def write_index(out: Path, items: list[Item], note: str = "") -> Path:
    side = out.with_suffix(".json")
    side.write_text(json.dumps({
        "sheet": str(out), "note": note,
        "cells": [{"cell": n, "key": it.key, "title": it.title, "date": it.date,
                   "licence": it.licence, "basis": it.basis, "landing_url": it.landing_url,
                   "attribution": it.attribution} for n, it in enumerate(items, 1)],
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    return side
