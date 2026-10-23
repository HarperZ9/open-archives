# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Zain Dana Harper
"""The local library: where downloads land, space and size guards, receipts."""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

from . import __version__
from .adapters import BY_NAME
from .model import Item
from .net import USER_AGENT, Http, SizeCapExceeded

log = logging.getLogger("openarchives.library")

MB = 1 << 20


def default_roots() -> list[str]:
    """Library candidates: $OPEN_ARCHIVES_ROOTS (os.pathsep-separated), else ~/archive-library."""
    env = os.environ.get("OPEN_ARCHIVES_ROOTS", "")
    roots = [r for r in env.split(os.pathsep) if r.strip()]
    return roots or [str(Path.home() / "archive-library")]


def forbidden_drives() -> set[str]:
    """Windows drive letters never written to, from $OPEN_ARCHIVES_FORBIDDEN_DRIVES (e.g. "D,F")."""
    env = os.environ.get("OPEN_ARCHIVES_FORBIDDEN_DRIVES", "")
    return {d.strip().rstrip(":").upper() for d in env.split(",") if d.strip()}


def drive_letter(path) -> str:
    """The Windows drive letter of a path on any platform, or an empty string."""
    return PureWindowsPath(str(path)).drive.rstrip(":").upper()


class LibraryError(RuntimeError):
    pass


def pick_root(explicit: str | None = None, need_bytes: int = 0, margin_mb: int = 2048) -> Path:
    """Choose the library root: explicit, then $OPEN_ARCHIVES_LIBRARY, then default_roots()."""
    candidates = [explicit] if explicit else []
    if os.environ.get("OPEN_ARCHIVES_LIBRARY") and not explicit:
        candidates.append(os.environ["OPEN_ARCHIVES_LIBRARY"])
    if not candidates:
        candidates = default_roots()
    problems = []
    for cand in candidates:
        path = Path(cand)
        drive = drive_letter(cand)
        if drive and drive in forbidden_drives():
            problems.append(f"{cand}: drive {drive}: is forbidden")
            continue
        anchor = Path(path.anchor or ".")
        if not anchor.exists():
            problems.append(f"{cand}: drive not present")
            continue
        free = shutil.disk_usage(anchor).free
        if free < need_bytes + margin_mb * MB:
            problems.append(f"{cand}: {free // MB} MB free, need {need_bytes // MB} + {margin_mb} MB margin")
            continue
        return path
    raise LibraryError("no usable library root: " + "; ".join(problems))


def safe_name(text: str, limit: int = 80) -> str:
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("._")
    return (s or "item")[:limit]


def safe_filename(name: str, limit: int = 120) -> str:
    """Like safe_name but keeps the file extension when the stem is truncated."""
    stem, dot, ext = name.rpartition(".")
    if not dot or not stem or len(ext) > 6:
        return safe_name(name, limit)
    ext = safe_name(ext, 6)
    return f"{safe_name(stem, limit - len(ext) - 1)}.{ext}"


@dataclass
class GatherPlan:
    cap_bytes: int = 300 * MB          # total per run
    per_file_bytes: int = 150 * MB
    files_per_item: int = 1
    skip_reference_only: bool = False


class Library:
    def __init__(self, root: Path):
        self.root = Path(root)
        drive = drive_letter(self.root)
        if drive and drive in forbidden_drives():
            raise LibraryError(f"refusing library on drive {drive}:")
        for sub in ("sources", "receipts", "assets", "sheets"):
            (self.root / sub).mkdir(parents=True, exist_ok=True)

    @property
    def index_path(self) -> Path:
        return self.root / "index.jsonl"

    def item_dir(self, item: Item) -> Path:
        return self.root / "sources" / item.source / safe_name(item.id)

    def gather(self, http: Http, items: list[Item], plan: GatherPlan, tag: str,
               query: dict | None = None) -> Path:
        free = shutil.disk_usage(self.root.anchor or ".").free
        if free < plan.cap_bytes + 2048 * MB:
            raise LibraryError(f"only {free // MB} MB free on {self.root.anchor}")
        spent = 0
        records = []
        for item in items:
            rec = {"item": None, "files": [], "status": "ok"}
            try:
                if plan.skip_reference_only and item.basis == "reference-only":
                    rec["status"] = "skipped: reference-only"
                else:
                    adapter = BY_NAME.get(item.source)
                    if adapter and not item.files:
                        adapter.resolve(http, item)
                    spent = self._fetch_files(http, item, plan, spent, rec)
            except Exception as exc:
                log.error("gather failed for %s: %s", item.key, exc)
                rec["status"] = f"error: {type(exc).__name__}: {exc}"[:300]
            rec["item"] = item.to_dict()
            records.append(rec)
            if rec["files"]:
                with open(self.index_path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps({"item": rec["item"], "files": rec["files"],
                                         "run": tag}, ensure_ascii=False) + "\n")
        return self._write_receipt(tag, query, plan, records, spent)

    def _fetch_files(self, http: Http, item: Item, plan: GatherPlan, spent: int, rec: dict) -> int:
        if not item.files:
            rec["status"] = "no downloadable file"
        for mf in item.files[: plan.files_per_item]:
            if mf.size and spent + mf.size > plan.cap_bytes:
                rec["status"] = f"skipped: run cap ({plan.cap_bytes // MB} MB) reached"
                break
            if mf.size and mf.size > plan.per_file_bytes:
                rec["status"] = f"skipped: file {mf.size // MB} MB over per-file cap"
                continue
            name = safe_filename(mf.name or mf.url.split("?")[0].rsplit("/", 1)[-1], 120)
            dest = self.item_dir(item) / name
            budget = min(plan.per_file_bytes, plan.cap_bytes - spent)
            try:
                size, digest = http.download(mf.url, dest, budget)
            except SizeCapExceeded as exc:
                rec["status"] = f"skipped: {exc}"
                continue
            spent += size
            rec["files"].append({"path": str(dest), "url": mf.url, "bytes": size,
                                 "sha256": digest, "kind": mf.kind})
        return spent

    def _write_receipt(self, tag, query, plan, records, spent) -> Path:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        bases = Counter(r["item"]["basis"] for r in records if r["files"])
        classes = Counter(r["item"]["licence"] for r in records if r["files"])
        receipt = {
            "tool": f"open-archives {__version__}", "user_agent": USER_AGENT,
            "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "tag": tag, "query": query,
            "caps": {"run_bytes": plan.cap_bytes, "per_file_bytes": plan.per_file_bytes},
            "bytes_downloaded": spent,
            "licence_breakdown": dict(classes), "basis_breakdown": dict(bases),
            "gate_rule": "unclear licence means reference-only; pd/cc0 free; cc-by credit; cc-by-sa share-alike",
            "items": records,
        }
        path = self.root / "receipts" / f"run-{stamp}-{safe_name(tag, 40)}.json"
        path.write_text(json.dumps(receipt, indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    def indexed(self) -> list[dict]:
        if not self.index_path.exists():
            return []
        with open(self.index_path, encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]
