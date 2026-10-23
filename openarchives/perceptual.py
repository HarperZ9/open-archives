# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Zain Dana Harper
"""Perceptual similarity for the clean-room gate. Pure Python, ffmpeg decodes.

Images: pHash (8x8 low-frequency DCT of a rank-equalised 32x32 luminance
window) plus dHash (gradient signs). Each derived window is compared with
many crops of the source at several scales and positions (the crop-and-tile
check), plus flips, and the best match counts. Equalising ranks first makes
the hash ignore brightness, contrast and most recolouring.

Audio lives in audioprint.py.
"""
from __future__ import annotations

import math

from . import mediatools as mt

N = 32
_COS = [[math.cos(math.pi * (2 * x + 1) * u / (2 * N)) for x in range(N)] for u in range(8)]


# ---------- images ----------

def _integral(w: int, h: int, px: bytes) -> list[list[int]]:
    ii = [[0] * (w + 1) for _ in range(h + 1)]
    for y in range(h):
        row, acc, prev, cur = px[y * w:(y + 1) * w], 0, ii[y], ii[y + 1]
        for x in range(w):
            acc += row[x]
            cur[x + 1] = prev[x + 1] + acc
    return ii


def _box(ii, x0: float, y0: float, ww: float, hh: float, n: int) -> list[float]:
    """Area-average the window into an n x n grid using the integral image."""
    out = []
    for gy in range(n):
        ya, yb = int(y0 + gy * hh / n), max(int(y0 + (gy + 1) * hh / n), int(y0 + gy * hh / n) + 1)
        for gx in range(n):
            xa, xb = int(x0 + gx * ww / n), max(int(x0 + (gx + 1) * ww / n), int(x0 + gx * ww / n) + 1)
            s = ii[yb][xb] - ii[ya][xb] - ii[yb][xa] + ii[ya][xa]
            out.append(s / ((yb - ya) * (xb - xa)))
    return out


def _equalise(v: list[float]) -> list[float]:
    order = sorted(range(len(v)), key=v.__getitem__)
    out = [0.0] * len(v)
    for r, i in enumerate(order):
        out[i] = float(r)
    return out


def phash(grid32: list[float]) -> int:
    g = _equalise(grid32)
    rows = [[sum(g[y * N + x] * _COS[u][x] for x in range(N)) for u in range(8)] for y in range(N)]
    coeffs = [sum(rows[y][u] * _COS[v][y] for y in range(N)) for v in range(8) for u in range(8)]
    med = sorted(coeffs[1:])[31]
    return sum(1 << i for i, c in enumerate(coeffs) if c > med)


def dhash(grid9x8: list[float]) -> int:
    bits, k = 0, 0
    for y in range(8):
        for x in range(8):
            if grid9x8[y * 9 + x + 1] > grid9x8[y * 9 + x]:
                bits |= 1 << k
            k += 1
    return bits


def _box_rect(ii, x0, y0, ww, hh, nx, ny):
    out = []
    for gy in range(ny):
        ya = int(y0 + gy * hh / ny); yb = max(int(y0 + (gy + 1) * hh / ny), ya + 1)
        for gx in range(nx):
            xa = int(x0 + gx * ww / nx); xb = max(int(x0 + (gx + 1) * ww / nx), xa + 1)
            out.append((ii[yb][xb] - ii[ya][xb] - ii[yb][xa] + ii[ya][xa]) / ((yb - ya) * (xb - xa)))
    return out


def source_windows(px_aspect: float = 0.0, sw: int = 1, sh: int = 1) -> list[tuple[float, float, float, float]]:
    """Candidate source crops (fractions) whose pixel aspect matches px_aspect.

    px_aspect 0 means "same aspect as the source". Scales run from the largest
    fitting window down to a quarter of it in 12% steps, with positions at a
    tenth-of-a-window stride.
    """
    if px_aspect <= 0:
        max_w, max_h = 1.0, 1.0
    elif px_aspect >= sw / sh:
        max_w, max_h = 1.0, (sw / px_aspect) / sh
    else:
        max_w, max_h = (sh * px_aspect) / sw, 1.0
    wins = []
    scale = 1.0
    while scale >= 0.24:
        fw, fh = max_w * scale, max_h * scale
        stride_x, stride_y = max(fw * 0.1, 1e-3), max(fh * 0.1, 1e-3)
        nx = int((1 - fw) / stride_x + 1e-9) + 1
        ny = int((1 - fh) / stride_y + 1e-9) + 1
        for iy in range(ny):
            for ix in range(nx):
                x = (1 - fw) * ix / (nx - 1) if nx > 1 else 0.0
                y = (1 - fh) * iy / (ny - 1) if ny > 1 else 0.0
                wins.append((x, y, fw, fh))
        scale *= 0.88
    return wins


DERIVED_WINDOWS = [(0, 0, 1, 1), (0, 0, .5, .5), (.5, 0, .5, .5), (0, .5, .5, .5),
                   (.5, .5, .5, .5), (.25, .25, .5, .5)]


def _flip(w, h, px: bytes, horizontal: bool) -> bytes:
    rows = [px[y * w:(y + 1) * w] for y in range(h)]
    if horizontal:
        rows = [r[::-1] for r in rows]
    else:
        rows = rows[::-1]
    return b"".join(rows)


def _sim(a: tuple[int, int], b: tuple[int, int]) -> float:
    return 1 - ((a[0] ^ b[0]).bit_count() + (a[1] ^ b[1]).bit_count()) / 128


def _hash_at(ii, w, h, win) -> tuple[int, int]:
    fx, fy, fw, fh = win
    x0, y0, ww, hh = fx * w, fy * h, fw * w, fh * h
    return phash(_box(ii, x0, y0, ww, hh, N)), dhash(_box_rect(ii, x0, y0, ww, hh, 9, 8))


def _dhash_at(ii, w, h, win) -> int:
    fx, fy, fw, fh = win
    return dhash(_box_rect(ii, fx * w, fy * h, fw * w, fh * h, 9, 8))


def _refine(ii, w, h, target, win, best) -> tuple[float, tuple]:
    """Hill-climb position and scale of a source window toward the target hash."""
    step, rounds = 0.04, 0
    while step > 0.005 and rounds < 30:
        rounds += 1
        improved = False
        fx, fy, fw, fh = win
        for dx, dy, ds in ((step, 0, 0), (-step, 0, 0), (0, step, 0), (0, -step, 0),
                           (0, 0, step), (0, 0, -step)):
            nw = min(max(fw + ds, 0.1), 1.0)
            nh = min(max(fh + ds * fh / fw, 0.1), 1.0)
            nx = min(max(fx + dx, 0.0), 1.0 - nw)
            ny = min(max(fy + dy, 0.0), 1.0 - nh)
            cand = (nx, ny, nw, nh)
            s = _sim(target, _hash_at(ii, w, h, cand))
            if s > best:
                best, win, improved = s, cand, True
        if not improved:
            step /= 2
    return best, win


def image_similarity(derived: str, source: str, width: int = 256, refine_top: int = 24,
                     per_window: int = 4) -> dict:
    sw, sh, spx = mt.decode_gray(source, width)
    dw, dh, dpx = mt.decode_gray(derived, width)
    s_ii = _integral(sw, sh, spx)
    wins = source_windows(dw / dh, sw, sh) + source_windows(0.0, sw, sh)
    # Coarse pass on the cheap gradient hash only; full hashes in refinement.
    src_d = [_dhash_at(s_ii, sw, sh, w) for w in wins]
    variants = {"as-is": dpx, "hflip": _flip(dw, dh, dpx, True), "vflip": _flip(dw, dh, dpx, False)}
    coarse = []
    for vname, px in variants.items():
        d_ii = _integral(dw, dh, px)
        for dwin in DERIVED_WINDOWS:
            target = _hash_at(d_ii, dw, dh, dwin)
            ranked = sorted((((target[1] ^ sd).bit_count(), swin) for swin, sd in zip(wins, src_d)),
                            key=lambda c: c[0])
            for _, swin in ranked[:per_window]:
                coarse.append((_sim(target, _hash_at(s_ii, sw, sh, swin)), vname, dwin, swin, target))
    coarse.sort(key=lambda c: -c[0])
    best, where = 0.0, None
    for s0, vname, dwin, swin, target in coarse[:refine_top]:
        s, swin2 = _refine(s_ii, sw, sh, target, swin, s0)
        if s > best:
            best, where = s, {"variant": vname, "derived_window": dwin,
                              "source_window": tuple(round(v, 3) for v in swin2)}
    return {"similarity": round(best, 4), "match": where}
