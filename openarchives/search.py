# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Zain Dana Harper
"""One query across every adapter: fan-out, filters, de-duplication, ranking."""
from __future__ import annotations

import logging
import math
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from . import licence as lic
from .adapters import ALL, BY_NAME, Adapter, Query
from .model import Item
from .net import Http

log = logging.getLogger("openarchives.search")

STOP = {"a", "an", "and", "the", "of", "in", "on", "for", "to", "with", "by", "or", "at"}
_TOKEN = re.compile(r"[a-z0-9]+")
FIELD_WEIGHTS = (("title", 3.0), ("subjects", 2.0), ("description", 1.0), ("creator", 0.5))


@dataclass
class Filters:
    year_from: int | None = None
    year_to: int | None = None
    strict_era: bool = False          # drop items with no parseable year
    licences: set[str] = field(default_factory=set)   # licence classes; empty = any
    bases: set[str] = field(default_factory=set)      # rights bases; empty = any
    media: tuple[str, ...] = ()


@dataclass
class SearchReport:
    items: list[Item]
    per_source: dict[str, int]
    errors: dict[str, str]
    skipped: dict[str, str]


def tokens(text: str) -> list[str]:
    return [t for t in _TOKEN.findall((text or "").lower()) if t not in STOP]


def choose_adapters(names: list[str] | None, q: Query) -> tuple[list[Adapter], dict[str, str]]:
    skipped: dict[str, str] = {}
    pool = [BY_NAME[n] for n in names] if names else [a for a in ALL if a.default]
    chosen = []
    for a in pool:
        if not a.supports(q):
            continue
        if not a.available():
            skipped[a.name] = f"needs key in {a.key_env}"
            continue
        chosen.append(a)
    return chosen, skipped


def run(http: Http, q: Query, filters: Filters, sources: list[str] | None = None,
        workers: int = 8) -> SearchReport:
    adapters, skipped = choose_adapters(sources, q)
    results: dict[str, list[Item]] = {}
    errors: dict[str, str] = {}

    def one(a: Adapter):
        try:
            return a.name, a.search(http, q), None
        except Exception as exc:  # reported per source, never swallowed
            log.error("source %s failed: %s", a.name, exc)
            return a.name, [], f"{type(exc).__name__}: {exc}"[:300]

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for name, items, err in pool.map(one, adapters):
            results[name] = items
            if err:
                errors[name] = err
    merged = dedupe([i for items in results.values() for i in items])
    kept = [i for i in merged if passes(i, filters)]
    rank(kept, q.text)
    return SearchReport(kept, {k: len(v) for k, v in results.items()}, errors, skipped)


def dedupe(items: list[Item]) -> list[Item]:
    seen: dict[str, Item] = {}
    for it in items:
        family = "ia" if it.source.startswith("ia_") or it.source in ("internet_archive", "musopen") else it.source
        k = f"{family}:{it.id}"
        if k not in seen or it.rank < seen[k].rank:
            seen[k] = it
    return list(seen.values())


def passes(item: Item, f: Filters) -> bool:
    if f.media:
        wanted = set(f.media)
        if "texture" in wanted:
            wanted.add("image")
        if item.media_type not in wanted:
            return False
    if f.licences and item.licence not in f.licences:
        return False
    if f.bases and item.basis not in f.bases:
        return False
    if f.year_from or f.year_to:
        y = item.year
        if y is None:
            return not f.strict_era
        if f.year_from and y < f.year_from:
            return False
        if f.year_to and y > f.year_to:
            return False
    return True


def rank(items: list[Item], query: str) -> None:
    """Score = BM25-style lexical relevance (fields weighted) fused with each
    source's own rank (reciprocal rank). Sorts in place, best first."""
    qt = tokens(query)
    if not items:
        return
    docs = [_field_tokens(i) for i in items]
    n = len(items)
    df = {t: sum(1 for d in docs if any(t in toks for toks in d.values())) for t in qt}
    lex = []
    for d in docs:
        s = 0.0
        for fname, w in FIELD_WEIGHTS:
            toks = d.get(fname, [])
            length = max(len(toks), 1)
            for t in qt:
                tf = toks.count(t)
                if tf:
                    idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
                    s += w * idf * tf * 2.2 / (tf + 1.2 * (0.25 + 0.75 * length / 12))
        lex.append(s)
    top = max(lex) or 1.0
    phrase = query.lower().strip()
    for it, s in zip(items, lex):
        rrf = 10.0 / (10.0 + it.rank)
        bonus = 0.1 if phrase and phrase in it.title.lower() else 0.0
        it.score = round(0.7 * (s / top) + 0.3 * rrf + bonus, 4)
    items.sort(key=lambda i: -i.score)


def _field_tokens(it: Item) -> dict[str, list[str]]:
    return {"title": tokens(it.title), "subjects": tokens(" ".join(it.subjects)),
            "description": tokens(it.description)[:300], "creator": tokens(it.creator or "")}


def parse_licence_filter(spec: str | None) -> tuple[set[str], set[str]]:
    """'pd,cc0' gives licence classes; 'shippable' or basis names give bases."""
    classes, bases = set(), set()
    for part in (spec or "").split(","):
        part = part.strip().lower()
        if not part:
            continue
        if part == "shippable":
            bases |= set(lic.SHIPPABLE)
        elif part in lic.BASES:
            bases.add(part)
        elif part in lic.LICENCE_CLASSES:
            classes.add(part)
        else:
            raise ValueError(f"unknown licence filter {part!r}")
    return classes, bases
