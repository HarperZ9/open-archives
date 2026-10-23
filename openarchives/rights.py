# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Zain Dana Harper
"""Asset receipts, lineage, rights overrides, the basis report and credits."""
from __future__ import annotations

import json
import time
from collections import defaultdict
from pathlib import Path

from . import __version__
from . import licence as lic
from . import mediatools as mt
from .net import sha256_file

OWN_WORK = lic.OWN_WORK


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


class AssetStore:
    """Receipts live in <library>/assets/<asset_id>.json."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.dir = self.root / "assets"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.overrides_path = self.root / "rights-overrides.jsonl"

    # ---------- lookup ----------
    def _index(self) -> list[dict]:
        path = self.root / "index.jsonl"
        if not path.exists():
            return []
        with open(path, encoding="utf-8") as fh:
            return [json.loads(l) for l in fh if l.strip()]

    def overrides(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        if self.overrides_path.exists():
            for line in self.overrides_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    rec = json.loads(line)
                    out[rec["key"]] = rec   # latest wins; history stays in the file
        return out

    def effective_basis(self, key: str, default: str) -> tuple[str, str]:
        o = self.overrides().get(key)
        return (o["basis"], o["reason"]) if o else (default, "licence gate")

    def describe_file(self, path: str) -> dict:
        """Lineage entry for a file: a library item, an asset, or an unknown file."""
        p = Path(path)
        digest = sha256_file(p)
        for rec in self._index():
            for f in rec["files"]:
                if f["sha256"] == digest or Path(f["path"]) == p:
                    it = rec["item"]
                    basis, why = self.effective_basis(it["key"], it["basis"])
                    return {"path": str(p), "sha256": digest, "item_key": it["key"],
                            "title": it["title"], "landing_url": it["landing_url"],
                            "source_url": f["url"], "licence": it["licence"],
                            "basis": basis, "basis_reason": why,
                            "attribution": it["attribution"]}
        for rec in self.all_assets():
            if rec["sha256"] == digest:
                return {"path": str(p), "sha256": digest, "asset_id": rec["asset_id"],
                        "basis": rec["basis"], "licence": "derived",
                        "attribution": "; ".join(i.get("attribution", "") for i in rec["inputs"]),
                        "lineage": rec["inputs"] + rec.get("references", [])}
        return {"path": str(p), "sha256": digest, "licence": lic.UNKNOWN,
                "basis": lic.REFERENCE_ONLY, "basis_reason": "file not in the library"}

    # ---------- receipts ----------
    def save(self, rec: dict) -> Path:
        path = self.dir / f"{rec['asset_id']}.json"
        path.write_text(json.dumps(rec, indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    def load(self, asset_id_or_path: str) -> dict:
        cand = self.dir / f"{asset_id_or_path}.json"
        if cand.exists():
            return json.loads(cand.read_text(encoding="utf-8"))
        digest = sha256_file(Path(asset_id_or_path))
        for rec in self.all_assets():
            if rec["sha256"] == digest:
                return rec
        raise KeyError(f"no asset receipt for {asset_id_or_path}")

    def all_assets(self) -> list[dict]:
        return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(self.dir.glob("*.json"))]

    def _base(self, out: str, kind: str) -> dict:
        p = Path(out)
        digest = sha256_file(p)
        return {"asset_id": digest[:16], "path": str(p), "sha256": digest,
                "bytes": p.stat().st_size, "kind": kind, "created": now(),
                "tool": f"open-archives {__version__}"}

    def record_derived(self, out: str, op: str, params: dict, inputs: list[str]) -> dict:
        rec = self._base(out, "derived")
        rec["operation"] = {"op": op, "params": params, "ffmpeg": mt.ffmpeg_version()}
        rec["inputs"] = [self.describe_file(i) for i in inputs]
        rec["references"] = []
        rec["basis"] = lic.derived_basis([i["basis"] for i in rec["inputs"]])
        rec["basis_reason"] = "most restrictive basis among inputs"
        rec["clean_room"] = None
        self.save(rec)
        return rec

    def register(self, path: str, references: list[str], note: str, author: str = "author") -> dict:
        """Record an independently made asset and the sources that were in view."""
        rec = self._base(path, "own-work")
        rec["operation"] = {"op": "register", "note": note, "made_by": author}
        rec["inputs"] = []
        rec["references"] = [self.describe_file(r) for r in references]
        rec["basis"] = OWN_WORK
        rec["basis_reason"] = "independent work; clean-room gate must pass before shipping"
        rec["clean_room"] = None
        self.save(rec)
        return rec

    def set_basis(self, key: str, basis: str, reason: str, use: str | None = None) -> dict:
        if basis not in lic.BASES:
            raise ValueError(f"unknown basis {basis!r}")
        if basis in (lic.FAIR_USE, lic.LICENSED) and len(reason.strip()) < 20:
            raise ValueError(f"{basis} needs a written reason (who, what use, why)")
        rec = {"key": key, "basis": basis, "reason": reason, "use": use, "date": now()}
        with open(self.overrides_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return rec


def shippable(rec: dict) -> bool:
    if rec["basis"] == lic.REFERENCE_ONLY:
        return False
    gate = rec.get("clean_room") or {}
    return gate.get("verdict") in (None, "pass", "not-needed") if rec["basis"] != OWN_WORK \
        else gate.get("verdict") in ("pass", "not-needed")


def basis_report(store: AssetStore) -> dict:
    """Which assets rest on which basis, and which are blocked."""
    groups: dict[str, list] = defaultdict(list)
    blocked = []
    for rec in store.all_assets():
        override = store.overrides().get(rec["asset_id"])
        if override:
            rec["basis"], rec["basis_reason"] = override["basis"], override["reason"]
        entry = {"asset_id": rec["asset_id"], "path": rec["path"], "basis": rec["basis"],
                 "why": rec.get("basis_reason"),
                 "gate": (rec.get("clean_room") or {}).get("verdict", "not run"),
                 "sources": [i.get("item_key") or i.get("asset_id") or i["path"]
                             for i in rec["inputs"] + rec.get("references", [])]}
        (groups[rec["basis"]] if shippable(rec) else blocked).append(entry)
    items: dict[str, int] = defaultdict(int)
    for row in store._index():
        basis, _ = store.effective_basis(row["item"]["key"], row["item"]["basis"])
        items[basis] += 1
    return {"shippable_assets": dict(groups), "blocked_assets": blocked,
            "library_items_by_basis": dict(items)}


def credits_markdown(store: AssetStore) -> str:
    lines = ["# Credits", "", "Generated by open-archives from asset receipts.", ""]
    seen = set()
    for rec in store.all_assets():
        if not shippable(rec):
            continue
        for src in rec["inputs"]:
            att = src.get("attribution")
            if att and att not in seen:
                seen.add(att)
                note = {lic.FREE: "public domain or CC0, credited as a courtesy",
                        lic.CREDIT: "credit required", lic.SHARE_ALIKE: "credit required, share-alike",
                        lic.FAIR_USE: "fair use (commentary or critique)", lic.LICENSED: "licensed"}.get(src["basis"], src["basis"])
                lines.append(f"- {att} ({note})")
    if len(lines) == 4:
        lines.append("- No shipped asset draws on outside material yet.")
    return "\n".join(lines) + "\n"
