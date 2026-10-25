#!/usr/bin/env python3
"""Fill the blank `arena` on captured X records from the study config's actor→arena mapping (#336).

**Dry run by default.** A write here is a bulk write over the production collection, so it needs an
explicit ``--apply`` (and the runbook's "ask first" applies to running it at all).

What it does, and only this:

* an ``x`` record whose ``arena`` is empty is matched by its ``source.author`` handle against
  ``groups[].accounts.x`` in the study config;
* on a match, ``arena`` (top level, which is what ``handoff.arena`` and the corpus audit read),
  ``source.raw_metadata.arena`` and ``source.raw_metadata.source_name`` are written — the last two
  only when absent, so a value the capture already recorded is never overwritten;
* no other field, collection or platform is touched, and an unmatched handle is counted as
  unattributed rather than guessed at.

**External-link children are not backfilled here.** A child record carries no handle of its own; its
arena came from its parent (`capture_server.py:390`), and the stored child keeps no parent handle to
re-derive it from. The forward fix in this change stops new children from being born blank; the
existing ones need the parent relation, which is a separate decision (see the issue).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

from laclaugpt_data_collection.attribution import match_account
from laclaugpt_data_collection.study import load_config

PROJECT = "ai26"


def _load_env(root: Path) -> dict[str, str]:
    env = dict(os.environ)
    candidate = root / ".env"
    if candidate.is_file():
        for line in candidate.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            env.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    return env


def _blank(value: object) -> bool:
    return not str(value or "").strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study-config", required=True, type=Path)
    parser.add_argument("--apply", action="store_true", help="write the updates (default: dry run)")
    parser.add_argument("--limit", type=int, default=0, help="stop after N updates (0: no bound)")
    parser.add_argument("--collection", default=f"{PROJECT}__records")
    parser.add_argument("--sample", type=int, default=5, help="print this many example updates")
    args = parser.parse_args(argv)

    from pymongo import MongoClient

    config = load_config(str(args.study_config))
    rows = [row for row in config.accounts() if row.get("arena")]
    if not rows:
        print("no group rows carry an arena in this study config; nothing to apply", file=sys.stderr)
        return 2

    env = _load_env(Path.cwd())
    uri = env.get("LACLAUGPT_MONGODB_URI", "")
    database = env.get("LACLAUGPT_MONGODB_DATABASE", "")
    if not uri or not database:
        print("LACLAUGPT_MONGODB_URI and LACLAUGPT_MONGODB_DATABASE must be set", file=sys.stderr)
        return 2
    collection = MongoClient(uri)[database][args.collection]

    query = {"project_id": PROJECT, "source.platform": "x", "arena": {"$in": ["", None]}}
    counts: Counter[str] = Counter()
    written = 0
    shown = 0

    for document in collection.find(
        query, {"source": 1, "arena": 1, "handoff": 1, "source_url": 1}
    ):
        counts["scanned"] += 1
        source = document.get("source") or {}
        handle = str(source.get("author") or "").lstrip("@")
        row = match_account(rows, "x", f"https://x.com/{handle}") if handle else None
        if row is None:
            counts["unattributed"] += 1
            continue
        arena = str(row.get("arena") or "")
        metadata = dict(source.get("raw_metadata") or {})
        update: dict[str, object] = {"arena": arena}
        metadata_updates: dict[str, object] = {}
        if _blank(metadata.get("arena")):
            metadata_updates["source.raw_metadata.arena"] = arena
        if _blank(metadata.get("source_name")):
            metadata_updates["source.raw_metadata.source_name"] = str(row.get("name") or "")
        update.update(metadata_updates)
        counts["mapped"] += 1
        if shown < args.sample:
            print(json.dumps({
                "source_url": document.get("source_url", ""),
                "handle": handle,
                "arena": arena,
                "fields": sorted(update),
            }, ensure_ascii=False))
            shown += 1
        if args.apply:
            collection.update_one({"_id": document["_id"]}, {"$set": update})
            written += 1
            if args.limit and written >= args.limit:
                counts["limit_reached"] += 1
                break

    verb = "updated" if args.apply else "would update"
    print(
        f"{verb} {written if args.apply else counts['mapped']} of {counts['scanned']} scanned "
        f"blank-arena X record(s); unattributed handles: {counts['unattributed']}; "
        f"mode={'apply' if args.apply else 'dry-run'}"
    )
    if not args.apply:
        print("nothing was written; re-run with --apply after approval")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
