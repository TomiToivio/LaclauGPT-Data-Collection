#!/usr/bin/env python3
"""Backfill the blank `arena` on captured X records from the study's declared mapping (#336).

**Dry run by default** — it prints what it would change and writes nothing. ``--apply`` performs the
write; the runbook's "ask first" rule applies to deciding to run it, not to the script's default.

Only X records with a blank top-level ``arena`` are considered, and only by their ``source.author``
handle. A handle no group declares is counted as unattributed, never guessed at. External-link
children are not touched: they carry no handle of their own, and their arena came from a parent the
stored record no longer names.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

from laclaugpt_data_collection.arena_backfill import plan_update
from laclaugpt_data_collection.study import load_config

PROJECT = "ai26"


def _env(root: Path) -> dict[str, str]:
    env = dict(os.environ)
    dotenv = root / ".env"
    if dotenv.is_file():
        for line in dotenv.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                env.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    return env


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study-config", required=True, type=Path)
    parser.add_argument("--apply", action="store_true", help="write the updates (default: dry run)")
    parser.add_argument("--limit", type=int, default=0, help="stop after N writes (0: no bound)")
    parser.add_argument("--collection", default=f"{PROJECT}__records")
    parser.add_argument("--sample", type=int, default=5, help="print this many planned updates")
    args = parser.parse_args(argv)

    from pymongo import MongoClient

    rows = [row for row in load_config(str(args.study_config)).accounts() if row.get("arena")]
    if not rows:
        print("no declared account row carries an arena; nothing to apply", file=sys.stderr)
        return 2

    env = _env(Path.cwd())
    uri = env.get("LACLAUGPT_MONGODB_URI", "")
    database = env.get("LACLAUGPT_MONGODB_DATABASE", "")
    if not uri or not database:
        print("LACLAUGPT_MONGODB_URI and LACLAUGPT_MONGODB_DATABASE must be set", file=sys.stderr)
        return 2
    collection = MongoClient(uri)[database][args.collection]

    counts: Counter[str] = Counter()
    writes = 0
    for document in collection.find(
        {"project_id": PROJECT, "source.platform": "x", "arena": {"$in": ["", None]}},
        {"source": 1, "arena": 1, "source_url": 1},
    ):
        counts["scanned"] += 1
        update = plan_update(document, rows)
        if update is None:
            counts["unattributed"] += 1
            continue
        counts["planned"] += 1
        if writes < args.sample:
            print(json.dumps({
                "source_url": document.get("source_url", ""),
                "handle": (document.get("source") or {}).get("author", ""),
                "set": update,
            }, ensure_ascii=False))
        if args.apply:
            collection.update_one({"_id": document["_id"]}, {"$set": update})
            writes += 1
            if args.limit and writes >= args.limit:
                counts["limit_reached"] += 1
                break

    done = writes if args.apply else counts["planned"]
    print(
        f"{'updated' if args.apply else 'would update'} {done} of {counts['scanned']} scanned "
        f"blank-arena X record(s); unattributed handles: {counts['unattributed']}; "
        f"mode={'apply' if args.apply else 'dry-run'}"
    )
    if not args.apply:
        print("nothing was written; re-run with --apply")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
