# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Zain Dana Harper
"""Commands for sheets, any-URL fetch, derive, register, the gate and rights."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from . import cleanroom, derive, sheets, webfetch
from .library import Library, pick_root
from .model import Item
from .net import Http
from .rights import AssetStore, basis_report, credits_markdown

log = logging.getLogger("openarchives.cli")


def _store(a) -> tuple[Library, AssetStore]:
    lib = Library(pick_root(getattr(a, "library", None)))
    return lib, AssetStore(lib.root)


def sheets_for_receipt(http: Http, lib: Library, receipt: Path) -> list[Path]:
    data = json.loads(receipt.read_text(encoding="utf-8"))
    stem = receipt.stem
    made: list[Path] = []
    images, audio, image_items, audio_items = [], [], [], []
    for n, rec in enumerate(data["items"], 1):
        it = Item.from_dict(rec["item"])
        for f in rec["files"]:
            kind = cleanroom.kind_of(f["path"])
            label = f"{n} {it.licence}"
            if kind == "image":
                images.append((f["path"], label)); image_items.append(it)
            elif kind == "audio":
                audio.append((f["path"], label)); audio_items.append(it)
            elif kind == "video":
                out = lib.root / "sheets" / f"{stem}_video{n:02d}.jpg"
                try:
                    made.append(sheets.video_sheet(f["path"], out))
                    sheets.write_index(out, [it], note=f"frames of {f['path']}")
                except Exception as exc:
                    log.error("video sheet failed for %s: %s", f["path"], exc)
    if images:
        out = lib.root / "sheets" / f"{stem}_images.jpg"
        made.append(sheets.image_grid(images, out))
        sheets.write_index(out, image_items)
    if audio:
        out = lib.root / "sheets" / f"{stem}_audio.jpg"
        made.append(sheets.audio_sheet(audio, out))
        sheets.write_index(out, audio_items)
    for m in made:
        print(f"sheet: {m}")
    return made


def stream_sheets(http: Http, results: Path, out: Path, pick: str | None) -> list[Path]:
    """Frame sheets for video results without downloading: ffmpeg seeks by range."""
    from .adapters import BY_NAME
    data = json.loads(results.read_text(encoding="utf-8"))
    items = [Item.from_dict(d) for d in data["items"]]
    chosen = [int(x) for x in pick.split(",")] if pick else range(1, len(items) + 1)
    made = []
    for n in chosen:
        it = items[n - 1]
        if it.media_type != "video":
            continue
        if not it.files and it.source in BY_NAME:
            BY_NAME[it.source].resolve(http, it)
        if not it.files:
            log.warning("no video file for %s", it.key)
            continue
        dest = out.parent / f"{out.stem}_{n:02d}_{it.id[:40]}.jpg"
        try:
            made.append(sheets.video_sheet(it.files[0].url, dest))
            sheets.write_index(dest, [it], note=f"streamed frames of {it.files[0].url}")
            print(f"sheet: {dest}")
        except Exception as exc:
            log.error("stream sheet failed for %s: %s", it.key, exc)
    return made


def cmd_sheet(http: Http, a):
    out = Path(a.out)
    if a.kind == "video":
        print(sheets.video_sheet(a.inputs[0], out, a.cols, a.rows))
    elif a.kind == "images":
        print(sheets.image_grid([(p, str(i)) for i, p in enumerate(a.inputs, 1)], out, a.cols))
    elif a.kind == "audio":
        print(sheets.audio_sheet([(p, Path(p).stem[:30]) for p in a.inputs], out))
    elif a.kind == "receipt":
        lib = Library(Path(a.inputs[0]).parents[1])
        sheets_for_receipt(http, lib, Path(a.inputs[0]))
    elif a.kind == "stream":
        stream_sheets(http, Path(a.inputs[0]), out, a.pick)
    elif a.kind == "results":
        data = json.loads(Path(a.inputs[0]).read_text(encoding="utf-8"))
        items = [Item.from_dict(d) for d in data["items"]]
        out.parent.mkdir(parents=True, exist_ok=True)
        work = out.parent / (out.stem + "_thumbs")
        entries = sheets.thumbs_for(http, items, work)
        print(sheets.image_grid(entries, out, a.cols))
        sheets.write_index(out, items, note="thumbnails of saved search results")


def cmd_fetch(http: Http, a):
    lib, _ = _store(a)
    receipt = webfetch.fetch(http, lib, a.url, a.licence, a.basis, a.reason or "",
                             a.terms_note or "", a.media, a.tag)
    print(f"receipt: {receipt}")


def cmd_derive(http: Http, a):
    _, store = _store(a)
    if a.op == "clip":
        rec = derive.clip(store, a.input, a.out, a.start, a.length, a.width)
    elif a.op == "audio":
        rec = derive.audio_cut(store, a.input, a.out, a.start, a.length, a.fade, a.normalise)
    elif a.op == "loop":
        rec = derive.audio_loop(store, a.input, a.out, a.start, a.length, a.fade, True)
    elif a.op == "crop":
        x, y, w, h = (int(v) for v in a.region.split(","))
        rec = derive.crop(store, a.input, a.out, x, y, w, h)
    elif a.op == "texture":
        region = tuple(int(v) for v in a.region.split(",")) if a.region else None
        rec = derive.texture(store, a.input, a.out, a.size, region, a.mode)
    elif a.op == "grade":
        rec = derive.grade(store, a.input, a.out, a.hue, a.saturation, a.gamma)
    elif a.op == "pitch":
        rec = derive.pitch(store, a.input, a.out, a.semitones, a.length or None)
    else:
        raise SystemExit(f"unknown op {a.op}")
    print(json.dumps({k: rec[k] for k in ("asset_id", "path", "basis", "basis_reason")}, indent=2))


def cmd_register(http: Http, a):
    _, store = _store(a)
    rec = store.register(a.file, a.ref or [], a.note)
    print(json.dumps({k: rec[k] for k in ("asset_id", "path", "basis", "basis_reason")}, indent=2))


def cmd_check(http: Http, a):
    _, store = _store(a)
    gate = cleanroom.check_derived(store, a.asset)
    print(json.dumps(gate, indent=2))
    if gate["verdict"] == "fail":
        raise SystemExit(2)


def cmd_rights(http: Http, a):
    _, store = _store(a)
    print(json.dumps(store.set_basis(a.key, a.basis, a.reason, a.use), indent=2))


def cmd_basis(http: Http, a):
    _, store = _store(a)
    rep = basis_report(store)
    if a.json:
        print(json.dumps(rep, indent=2))
        return
    for basis, rows in rep["shippable_assets"].items():
        print(f"[{basis}] {len(rows)} asset(s)")
        for r in rows:
            print(f"   {r['asset_id']} gate={r['gate']:10} {Path(r['path']).name}  <- {', '.join(r['sources'])}")
    print(f"[blocked] {len(rep['blocked_assets'])} asset(s)")
    for r in rep["blocked_assets"]:
        print(f"   {r['asset_id']} basis={r['basis']} gate={r['gate']} {Path(r['path']).name}")
    print(f"library items by basis: {rep['library_items_by_basis']}")


def cmd_credits(http: Http, a):
    _, store = _store(a)
    text = credits_markdown(store)
    out = Path(a.out) if a.out else store.root / "CREDITS.md"
    out.write_text(text, encoding="utf-8")
    print(f"credits: {out}")


def add_commands(sub, library_args) -> None:
    _add_review(sub, library_args)
    _add_derive(sub, library_args)
    _add_rights(sub, library_args)


def _add_review(sub, library_args) -> None:
    sh = sub.add_parser("sheet", help="contact sheet: video, images, audio, receipt or results")
    sh.add_argument("kind", choices=["video", "images", "audio", "receipt", "results", "stream"])
    sh.add_argument("inputs", nargs="+", help="files, URLs, a receipt or a results JSON")
    sh.add_argument("--out", default="sheet.jpg")
    sh.add_argument("--cols", type=int, default=6)
    sh.add_argument("--rows", type=int, default=3)
    sh.add_argument("--pick", help="stream: comma list of result numbers")
    sh.set_defaults(fn=cmd_sheet)

    f = sub.add_parser("fetch", help="any URL: robots.txt honoured, rights basis recorded")
    f.add_argument("url")
    f.add_argument("--licence", help="licence you confirmed for this material")
    f.add_argument("--basis", help="basis override (fair-use, licensed, ...); needs --reason")
    f.add_argument("--reason", help="why the basis holds (required for fair-use and licensed)")
    f.add_argument("--terms-note", help="what the person found in the site's terms")
    f.add_argument("--media", type=int, default=0, help="also fetch up to N media links on the page")
    f.add_argument("--tag", default="web")
    library_args(f)
    f.set_defaults(fn=cmd_fetch)


def _add_derive(sub, library_args) -> None:
    d = sub.add_parser("derive", help="cut, crop, texture, grade or pitch, with lineage")
    d.add_argument("op", choices=["clip", "audio", "loop", "crop", "texture", "grade", "pitch"])
    d.add_argument("input")
    d.add_argument("out")
    d.add_argument("--start", type=float, default=0.0)
    d.add_argument("--length", type=float, default=10.0)
    d.add_argument("--width", type=int)
    d.add_argument("--fade", type=float, default=0.3, help="fade seconds (loop: crossfade)")
    d.add_argument("--normalise", action="store_true")
    d.add_argument("--region", help="x,y,w,h")
    d.add_argument("--size", type=int, default=1024)
    d.add_argument("--mode", default="mirror", choices=["mirror", "plain"])
    d.add_argument("--hue", type=float, default=0.0)
    d.add_argument("--saturation", type=float, default=1.0)
    d.add_argument("--gamma", type=float, default=1.0)
    d.add_argument("--semitones", type=float, default=0.0)
    library_args(d)
    d.set_defaults(fn=cmd_derive)


def _add_rights(sub, library_args) -> None:
    r = sub.add_parser("register", help="record an independently made asset and its references")
    r.add_argument("file")
    r.add_argument("--ref", nargs="*", help="library files that were in view while making it")
    r.add_argument("--note", default="")
    library_args(r)
    r.set_defaults(fn=cmd_register)

    c = sub.add_parser("check-derived", help="clean-room gate against reference-only sources")
    c.add_argument("asset", help="asset id or file path")
    library_args(c)
    c.set_defaults(fn=cmd_check)

    rs = sub.add_parser("rights", help="record a basis for an item key or asset id")
    rs.add_argument("key")
    rs.add_argument("--basis", required=True)
    rs.add_argument("--reason", required=True)
    rs.add_argument("--use", help="where it will ship (for fair use: the explainer)")
    library_args(rs)
    rs.set_defaults(fn=cmd_rights)

    b = sub.add_parser("basis", help="which assets ship on which basis")
    b.add_argument("--json", action="store_true")
    library_args(b)
    b.set_defaults(fn=cmd_basis)

    cr = sub.add_parser("credits", help="write CREDITS.md from asset receipts")
    cr.add_argument("--out")
    library_args(cr)
    cr.set_defaults(fn=cmd_credits)
