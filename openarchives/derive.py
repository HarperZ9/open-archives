# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Zain Dana Harper
"""Edit and repurpose: cut clips and audio, crop images, build tileable textures.

Every operation writes an asset receipt that carries the lineage from the
library source (with its licence and basis) to the derived file.
"""
from __future__ import annotations

from pathlib import Path

from . import mediatools as mt
from .rights import AssetStore


def clip(store: AssetStore, src: str, out: str, start: float, length: float,
         width: int | None = None, keep_audio: bool = True) -> dict:
    vf = ["-vf", f"scale={width}:-2"] if width else []
    audio = ["-c:a", "aac", "-b:a", "160k"] if keep_audio else ["-an"]
    mt.run(["-ss", str(start), "-i", src, "-t", str(length), *vf, "-c:v", "libx264",
            "-crf", "18", "-pix_fmt", "yuv420p", *audio, out])
    return store.record_derived(out, "clip", {"start": start, "length": length,
                                              "width": width, "audio": keep_audio}, [src])


def audio_cut(store: AssetStore, src: str, out: str, start: float, length: float,
              fade: float = 0.3, normalise: bool = False, rate: int = 48000) -> dict:
    fade_out_at = max(length - fade, 0)
    chain = [f"afade=t=in:d={fade}", f"afade=t=out:st={fade_out_at}:d={fade}"]
    if normalise:
        chain.append("loudnorm=I=-18:TP=-1.5:LRA=11")
    mt.run(["-ss", str(start), "-i", src, "-t", str(length), "-af", ",".join(chain),
            "-ar", str(rate), out])
    return store.record_derived(out, "audio_cut", {"start": start, "length": length,
                                                   "fade": fade, "normalise": normalise,
                                                   "rate": rate}, [src])


def audio_loop(store: AssetStore, src: str, out: str, start: float, length: float,
               crossfade: float = 1.0, normalise: bool = True, rate: int = 48000) -> dict:
    """Seamless loop: the audio just after the loop end is faded out over the
    faded-in head, so the end flows back into the start without a dip."""
    xf = min(crossfade, length / 2)
    dur = mt.duration(src)
    if dur is not None and start + length + xf > dur + 0.01:
        raise ValueError(f"source is {dur:.2f} s; a loop needs start + length + crossfade "
                         f"({start + length + xf:.2f} s) inside it")
    graph = (f"[0:a]atrim=0:{start + length + xf},asetpts=PTS-STARTPTS,aresample={rate},"
             f"asplit=2[x][y];[x]atrim={start}:{start + length},asetpts=PTS-STARTPTS,"
             f"afade=t=in:d={xf}[body];[y]atrim={start + length}:{start + length + xf},"
             f"asetpts=PTS-STARTPTS,afade=t=out:d={xf}[tail];"
             "[body][tail]amix=inputs=2:duration=first:normalize=0")
    gain = 0.0
    if normalise:
        # Static gain only: a dynamic normaliser would change level across the seam.
        tmp = str(Path(out).with_suffix(".unnormalised.wav"))
        mt.run(["-i", src, "-filter_complex", graph, "-ar", str(rate), tmp])
        peak = mt.peak_db(tmp)
        gain = round(-1.0 - peak, 2) if peak is not None else 0.0
        mt.run(["-i", tmp, "-af", f"volume={gain}dB", "-ar", str(rate), out])
        Path(tmp).unlink(missing_ok=True)
    else:
        mt.run(["-i", src, "-filter_complex", graph, "-ar", str(rate), out])
    return store.record_derived(out, "audio_loop", {"start": start, "length": length,
                                                    "crossfade": xf, "peak_gain_db": gain,
                                                    "rate": rate}, [src])


def crop(store: AssetStore, src: str, out: str, x: int, y: int, w: int, h: int) -> dict:
    mt.run(["-i", src, "-frames:v", "1", "-vf", f"crop={w}:{h}:{x}:{y}", out])
    return store.record_derived(out, "crop", {"x": x, "y": y, "w": w, "h": h}, [src])


def texture(store: AssetStore, src: str, out: str, size: int = 1024,
            region: tuple[int, int, int, int] | None = None, mode: str = "mirror",
            preview: bool = True) -> dict:
    """Make a seamless square texture source.

    mirror: crop a square, scale to size/2, mirror into a 2x2 block. Seamless
            by construction; best for organic surfaces (plaster, stone, cloth).
    plain:  crop a square and scale to size, for sources that already tile.
    A 3x3 repeat preview is written beside the output to check seams.
    """
    crop_f = f"crop={region[2]}:{region[3]}:{region[0]}:{region[1]}," if region else \
        "crop='min(iw,ih)':'min(iw,ih)',"
    if mode == "mirror":
        half = size // 2
        graph = (f"[0:v]{crop_f}scale={half}:{half},split=2[a][b];[b]hflip[bh];"
                 "[a][bh]hstack,split=2[top][t2];[t2]vflip[bot];[top][bot]vstack")
        mt.run(["-i", src, "-frames:v", "1", "-filter_complex", graph, out])
    elif mode == "plain":
        mt.run(["-i", src, "-frames:v", "1", "-vf", f"{crop_f}scale={size}:{size}", out])
    else:
        raise ValueError(f"unknown texture mode {mode!r}")
    params = {"size": size, "region": region, "mode": mode}
    rec = store.record_derived(out, "texture", params, [src])
    if preview:
        prev = str(Path(out).with_name(Path(out).stem + "_repeat3x3.jpg"))
        mt.run(["-i", out, "-frames:v", "1", "-filter_complex",
                "[0:v]split=3[a][b][c];[a][b][c]hstack=3,split=3[r1][r2][r3];[r1][r2][r3]vstack=3,"
                "scale=1200:-2", prev])
        rec["preview"] = prev
        store.save(rec)
    return rec


def grade(store: AssetStore, src: str, out: str, hue: float = 0, saturation: float = 1.0,
          gamma: float = 1.0) -> dict:
    """Colour-grade an image (also used to make the recolour control for the gate)."""
    mt.run(["-i", src, "-frames:v", "1", "-vf",
            f"hue=h={hue}:s={saturation},eq=gamma={gamma}", out])
    return store.record_derived(out, "grade", {"hue": hue, "saturation": saturation,
                                               "gamma": gamma}, [src])


def pitch(store: AssetStore, src: str, out: str, semitones: float, length: float | None = None) -> dict:
    """Pitch-shift audio, duration kept (rubberband)."""
    ratio = 2 ** (semitones / 12)
    t = ["-t", str(length)] if length else []
    mt.run(["-i", src, *t, "-af", f"rubberband=pitch={ratio:.5f}", out])
    return store.record_derived(out, "pitch", {"semitones": semitones, "length": length}, [src])
