# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Zain Dana Harper
"""Command line: search, gather, sources, sheets, fetch, derive, rights, gate."""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

from . import __version__, cli_media
from . import search as srch
from .adapters import ALL, BY_NAME, Query
from .library import MB, GatherPlan, Library, pick_root
from .model import MEDIA_TYPES, Item
from .net import Http

log = logging.getLogger("openarchives")


def _query_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("query", nargs="?", help="search words (archive query syntax passes through)")
    p.add_argument("--media", default="", help=f"comma list of {','.join(MEDIA_TYPES)}")
    p.add_argument("--from", dest="year_from", type=int, help="earliest year")
    p.add_argument("--to", dest="year_to", type=int, help="latest year")
    p.add_argument("--strict-era", action="store_true", help="drop items with no year")
    p.add_argument("--licence", help="licence classes (pd,cc0,cc-by,...) or bases (free,credit,shippable)")
    p.add_argument("--sources", help="comma list of adapter names (see `sources`)")
    p.add_argument("--limit", type=int, default=15, help="results per source")
    p.add_argument("--top", type=int, default=40, help="results kept after ranking")
    p.add_argument("--save", help="write ranked results to this JSON file")


def _library_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--library", help="library root (default $OPEN_ARCHIVES_LIBRARY, then $OPEN_ARCHIVES_ROOTS, "
                   "then ~/archive-library)")


def do_search(http: Http, a) -> list[Item]:
    if not a.query:
        raise SystemExit("a query is needed")
    media = tuple(m for m in a.media.split(",") if m)
    bad = [m for m in media if m not in MEDIA_TYPES]
    if bad:
        raise SystemExit(f"unknown media type(s): {bad}")
    classes, bases = srch.parse_licence_filter(a.licence)
    q = Query(a.query, media, a.year_from, a.year_to, a.limit)
    f = srch.Filters(a.year_from, a.year_to, a.strict_era, classes, bases, media)
    sources = [s.strip() for s in a.sources.split(",")] if a.sources else None
    if sources:
        unknown = [s for s in sources if s not in BY_NAME]
        if unknown:
            raise SystemExit(f"unknown source(s): {unknown}")
    rep = srch.run(http, q, f, sources)
    items = rep.items[: a.top]
    print(f"{len(rep.items)} results after filters; showing {len(items)}")
    for n, it in enumerate(items, 1):
        print(f"{n:3d} {it.score:5.2f} {it.source:18.18} {it.media_type:7.7} {str(it.year or ''):4} "
              f"{it.licence:12.12} {it.basis:14.14} {it.title[:70]}")
    for name, err in rep.errors.items():
        print(f"  error  {name}: {err}", file=sys.stderr)
    for name, why in rep.skipped.items():
        print(f"  skipped {name}: {why}", file=sys.stderr)
    if a.save:
        Path(a.save).write_text(json.dumps({
            "query": vars(q), "per_source": rep.per_source, "errors": rep.errors,
            "skipped": rep.skipped, "items": [i.to_dict() for i in items]},
            indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return items


def cmd_search(http, a):
    do_search(http, a)


def cmd_gather(http, a):
    if a.results:
        data = json.loads(Path(a.results).read_text(encoding="utf-8"))
        items = [Item.from_dict(d) for d in data["items"]]
        query = data.get("query")
    else:
        items = do_search(http, a)
        query = {"text": a.query, "media": a.media, "from": a.year_from, "to": a.year_to,
                 "licence": a.licence}
    if a.pick:
        picks = [int(x) for x in a.pick.split(",")]
        items = [items[i - 1] for i in picks if 0 < i <= len(items)]
    items = items[: a.max_items]
    plan = GatherPlan(cap_bytes=a.max_mb * MB, per_file_bytes=a.per_file_mb * MB,
                      files_per_item=a.files_per_item, skip_reference_only=a.skip_reference)
    lib = Library(pick_root(a.library, plan.cap_bytes))
    receipt = lib.gather(http, items, plan, a.tag, query)
    data = json.loads(receipt.read_text(encoding="utf-8"))
    print(f"receipt: {receipt}")
    print(f"downloaded {data['bytes_downloaded'] / MB:.1f} MB; licences {data['licence_breakdown']}; "
          f"bases {data['basis_breakdown']}")
    if a.sheet:
        cli_media.sheets_for_receipt(http, lib, receipt)


def cmd_sources(http, a):
    rows = []
    for ad in ALL:
        status = "ready" if ad.available() else f"needs key ({ad.key_env})"
        row = {"name": ad.name, "label": ad.label, "media": list(ad.media), "status": status,
               "default": ad.default, "docs": ad.docs, "docs_checked": ad.docs_checked, "note": ad.note}
        if a.probe and ad.available():
            t0 = time.monotonic()
            try:
                found = ad.search(http, Query(a.probe_query or "mill", ad.media[:1], limit=3))
                row["status"] = f"working ({len(found)} results)" if found else "working (0 results)"
                if found and ad.name in ("internet_archive", "nasa", "polyhaven", "fontsource") and a.resolve:
                    ad.resolve(http, found[0])
                    row["status"] += f", resolve gave {len(found[0].files)} file(s)"
            except Exception as exc:
                log.error("probe of %s failed: %s", ad.name, exc)
                row["status"] = f"broken: {type(exc).__name__}: {str(exc)[:150]}"
            row["seconds"] = round(time.monotonic() - t0, 1)
        rows.append(row)
        print(f"{ad.name:18} {row['status']:45.45} {ad.label}")
    if a.save:
        Path(a.save).write_text(json.dumps(rows, indent=2), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="open-archives", description=__doc__)
    p.add_argument("-V", "--version", action="version", version=__version__)
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("search", help="one query across every open archive")
    _query_args(s)
    s.set_defaults(fn=cmd_search)

    g = sub.add_parser("gather", help="search (or load saved results) and download with a receipt")
    _query_args(g)
    _library_args(g)
    g.add_argument("--results", help="saved results JSON from `search --save`")
    g.add_argument("--pick", help="comma list of result numbers to download")
    g.add_argument("--max-items", type=int, default=20)
    g.add_argument("--max-mb", type=int, default=300, help="total cap for this run")
    g.add_argument("--per-file-mb", type=int, default=150)
    g.add_argument("--files-per-item", type=int, default=1)
    g.add_argument("--skip-reference", action="store_true", help="download only shippable items")
    g.add_argument("--tag", default="gather")
    g.add_argument("--sheet", action="store_true", help="make contact sheets afterwards")
    g.set_defaults(fn=cmd_gather)

    so = sub.add_parser("sources", help="list adapters; --probe runs a live check")
    so.add_argument("--probe", action="store_true")
    so.add_argument("--probe-query")
    so.add_argument("--resolve", action="store_true", help="also resolve one file per probe")
    so.add_argument("--save")
    so.set_defaults(fn=cmd_sources)

    cli_media.add_commands(sub, _library_args)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")
    try:
        args.fn(Http(), args)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        log.error("%s failed: %s", args.cmd, exc)
        if args.verbose:
            raise
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0
