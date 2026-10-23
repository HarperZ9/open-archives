# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Zain Dana Harper
"""ffmpeg access: locate the binary, run it, decode pixels and samples.

The binary comes from $OPEN_ARCHIVES_FFMPEG, then the imageio_ffmpeg package
(an R&D convenience that bundles a static ffmpeg), then ffmpeg on PATH.
No Python media library is required.
"""
from __future__ import annotations

import functools
import logging
import os
import re
import shutil
import subprocess
from array import array
from pathlib import Path

log = logging.getLogger("openarchives.media")

FONT = "C\\:/Windows/Fonts/consola.ttf"


class FfmpegError(RuntimeError):
    pass


@functools.lru_cache(maxsize=1)
def ffmpeg_exe() -> str:
    env = os.environ.get("OPEN_ARCHIVES_FFMPEG")
    if env and Path(env).exists():
        return env
    try:
        import imageio_ffmpeg  # R&D tool, optional
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:  # fall through to PATH, but say why
        log.debug("imageio_ffmpeg unavailable: %s", exc)
    found = shutil.which("ffmpeg")
    if not found:
        raise FfmpegError("ffmpeg not found: set OPEN_ARCHIVES_FFMPEG or install imageio-ffmpeg")
    return found


@functools.lru_cache(maxsize=1)
def ffmpeg_version() -> str:
    out = subprocess.run([ffmpeg_exe(), "-version"], capture_output=True, text=True)
    return out.stdout.splitlines()[0] if out.stdout else "unknown"


def run(args: list[str], capture: bool = False, timeout: float = 600) -> bytes:
    cmd = [ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y", *args]
    proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
    if proc.returncode != 0:
        msg = proc.stderr.decode("utf-8", "replace")[-800:]
        log.error("ffmpeg failed: %s :: %s", " ".join(args[:8]), msg)
        raise FfmpegError(msg)
    return proc.stdout if capture else b""


def duration(src: str) -> float | None:
    """Seconds, parsed from ffmpeg's input banner (works for files and URLs)."""
    proc = subprocess.run([ffmpeg_exe(), "-hide_banner", "-i", src],
                          capture_output=True, text=True, errors="replace", timeout=120)
    m = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", proc.stderr)
    if not m:
        return None
    h, mnt, s = m.groups()
    return int(h) * 3600 + int(mnt) * 60 + float(s)


def peak_db(src: str) -> float | None:
    """Sample peak in dBFS (ffmpeg volumedetect)."""
    proc = subprocess.run([ffmpeg_exe(), "-hide_banner", "-i", src, "-af", "volumedetect",
                           "-f", "null", "-"], capture_output=True, text=True, errors="replace",
                          timeout=300)
    m = re.search(r"max_volume: (-?[\d.]+) dB", proc.stderr)
    return float(m.group(1)) if m else None


def decode_gray(src: str, width: int, height: int | None = None) -> tuple[int, int, bytes]:
    """Decode the first frame to 8-bit grayscale. height None keeps aspect."""
    h = height if height else -2
    raw = run(["-i", src, "-frames:v", "1", "-vf",
               f"scale={width}:{h}:flags=area,format=gray", "-f", "rawvideo", "pipe:1"],
              capture=True)
    hh = len(raw) // width
    return width, hh, raw[: width * hh]


def decode_audio(src: str, rate: int = 8000, seconds: float = 120.0) -> array:
    """Mono signed 16-bit samples at `rate`, first `seconds` only."""
    raw = run(["-i", src, "-t", str(seconds), "-ac", "1", "-ar", str(rate),
               "-f", "s16le", "pipe:1"], capture=True)
    samples = array("h")
    samples.frombytes(raw[: len(raw) // 2 * 2])
    return samples


def label_filter(text: str, size: int = 14) -> str:
    safe = re.sub(r"[^A-Za-z0-9 ._#:-]", "", text)[:40].replace(":", "\\:")
    return (f"drawtext=fontfile='{FONT}':text='{safe}':x=4:y=h-th-4:fontsize={size}:"
            "fontcolor=white:box=1:boxcolor=black@0.6:boxborderw=3")
