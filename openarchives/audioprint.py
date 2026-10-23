# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Zain Dana Harper
"""Audio fingerprint for the clean-room gate. Pure Python, ffmpeg decodes.

A spectral-shape fingerprint over semitone-spaced bands (a variant of the
Haitsma-Kalker scheme without the time difference). The match
searches time offsets (excerpts) and band shifts (pitch changes of up to
+/- 4 semitones) and reports 1 - bit error rate at the best alignment.
"""
from __future__ import annotations

import cmath
import math
from array import array

from . import mediatools as mt

RATE, FRAME, HOP = 8000, 1024, 256
FLOOR = 6.0                        # bands more than 60 dB below the loudest are floored
F_LO, N_BANDS = 130.0, 56          # semitone bands from ~130 Hz to ~3.2 kHz
MAX_SHIFT = 4


def _fft(x: list[complex]) -> list[complex]:
    n = len(x)
    if n == 1:
        return x
    even, odd = _fft(x[0::2]), _fft(x[1::2])
    tw = [cmath.exp(-2j * math.pi * k / n) * odd[k] for k in range(n // 2)]
    return [even[k] + tw[k] for k in range(n // 2)] + [even[k] - tw[k] for k in range(n // 2)]


def _band_edges() -> list[tuple[int, int]]:
    edges = []
    for b in range(N_BANDS):
        lo = F_LO * 2 ** ((b - 0.5) / 12)
        hi = F_LO * 2 ** ((b + 0.5) / 12)
        a, z = int(lo * FRAME / RATE), int(math.ceil(hi * FRAME / RATE))
        edges.append((a, max(z, a + 1)))
    return edges


_WIN = [0.5 - 0.5 * math.cos(2 * math.pi * i / FRAME) for i in range(FRAME)]


def band_energies(samples: array) -> list[list[float]]:
    """Log band energies per frame, floored 60 dB below the file's loudest band.

    The floor makes silent bands identical (difference exactly zero) instead of
    letting rounding noise in near-silence decide fingerprint bits.
    """
    edges = _band_edges()
    frames = []
    for start in range(0, len(samples) - FRAME, HOP):
        spec = _fft([complex(samples[start + i] * _WIN[i]) for i in range(FRAME)])
        power = [abs(c) ** 2 for c in spec[: FRAME // 2]]
        frames.append([math.log10(1e-6 + sum(power[a:z]) / (z - a)) for a, z in edges])
    if frames:
        floor = max(max(f) for f in frames) - FLOOR
        frames = [[v if v > floor else floor for v in f] for f in frames]
    return frames


def fingerprint_from(e: list[list[float]]) -> list[tuple[int, int]]:
    """Per frame: (bits, active). Bit b says band b is louder than band b+1
    (spectral shape). A bit is active when the two bands differ; floored
    silence on both sides carries no information.

    Shape bits beat Haitsma-Kalker time-difference bits on the controls:
    pitch-shifting smears note onsets, which scrambles time differences
    (pitched copy 0.58) while the spectral shape survives (0.77).
    """
    fp = []
    for frame in e:
        bits = active = 0
        for b in range(N_BANDS - 1):
            v = frame[b] - frame[b + 1]
            if v > 1e-9:
                bits |= 1 << b
            if abs(v) > 1e-9:
                active |= 1 << b
        fp.append((bits, active))
    return fp


def fingerprint(samples: array) -> list[tuple[int, int]]:
    return fingerprint_from(band_energies(samples))


def envelope(e: list[list[float]]) -> list[float]:
    """Log total energy per frame: survives pitch shifts and recolouring EQ."""
    return [math.log10(1e-6 + sum(10 ** v for v in frame)) for frame in e]


def envelope_match(d: list[float], s: list[float]) -> dict:
    """Best Pearson correlation of the shorter envelope slid along the longer."""
    short, long_ = (d, s) if len(d) <= len(s) else (s, d)
    n = len(short)
    if n < 40:
        return {"correlation": 0.0, "offset_frames": None, "note": "clip too short"}
    ms = sum(short) / n
    ss = math.sqrt(sum((x - ms) ** 2 for x in short)) or 1e-9
    best, at = -1.0, None
    for off in range(0, len(long_) - n + 1):
        seg = long_[off:off + n]
        ml = sum(seg) / n
        sl = math.sqrt(sum((x - ml) ** 2 for x in seg)) or 1e-9
        r = sum((a - ms) * (b - ml) for a, b in zip(short, seg)) / (ss * sl)
        if r > best:
            best, at = r, off
    return {"correlation": round(best, 4), "offset_frames": at}


def match_fingerprints(d: list[tuple[int, int]], s: list[tuple[int, int]]) -> dict:
    """Best agreement of derived d inside source s over time offsets and band
    shifts, counted over bits active in either side (1 - bit error rate)."""
    if not d or not s:
        return {"similarity": 0.0, "match": None}
    full = (1 << (N_BANDS - 1)) - 1
    best, where = 0.0, None
    short, long_ = (d, s) if len(d) <= len(s) else (s, d)
    span = len(short)
    for shift in range(-MAX_SHIFT, MAX_SHIFT + 1):
        mask = (full >> shift) << shift if shift >= 0 else full >> -shift
        moved = [((b << shift, a << shift) if shift >= 0 else (b >> -shift, a >> -shift))
                 for b, a in short]
        for off in range(0, len(long_) - span + 1):
            err = n = 0
            for i in range(span):
                b1, a1 = moved[i]
                b2, a2 = long_[off + i]
                valid = (a1 | a2) & mask
                n += valid.bit_count()
                err += ((b1 ^ b2) & valid).bit_count()
            if n < 20 * span:          # mostly silence: no evidence either way
                continue
            sim = 1 - err / n
            if sim > best:
                best, where = sim, {"offset_frames": off, "band_shift_semitones": shift,
                                    "active_bits": n}
    return {"similarity": round(best, 4), "match": where}


def audio_similarity(derived: str, source: str, seconds: float = 30.0) -> dict:
    de = band_energies(mt.decode_audio(derived, RATE, seconds))
    se = band_energies(mt.decode_audio(source, RATE, 120.0))
    out = match_fingerprints(fingerprint_from(de), fingerprint_from(se))
    out["envelope"] = envelope_match(envelope(de), envelope(se))
    return out
