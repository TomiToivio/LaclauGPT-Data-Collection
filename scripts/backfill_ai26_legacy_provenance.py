#!/usr/bin/env python3
"""Explicit, audited AI26 legacy attribution backfill (#250).

Read-only by default. The operator supplies a reviewed JSONL mapping with
record _id, expected source_url, arena and *evidence-backed* source_name.
Never infer arena from author/domain or mutate the 55 deferred X records.
"""
from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

ARENAS = frozenset({"elites", "grassroots", "parliamentary"})
PLATFORMS = frozenset({"rss", "web"})


def validate_mapping(row: dict) -> dict:
    required = ("id", "source_url", "platform", "arena", "source_name", "evidence")
    if not isinstance(row, dict) or any(not isinstance(row.get(k), str) or not row[k].strip() for k in required):
        raise ValueError(f"mapping needs nonempty strings: {', '.join(required)}")
    if row["platform"] not in PLATFORMS or row["arena"] not in ARENAS:
        raise ValueError("only RSS/web and declared AI26 arenas can be backfilled")
    if urlsplit(row["source_url"]).scheme not in ("http", "https"):
        raise ValueError("source_url must be an HTTP(S) canonical URL")
    if len(row["evidence"].strip()) < 15:
        raise ValueError("record-specific source attribution evidence is required")
    return row


def load_mappings(path: Path) -> list[dict]:
    seen = set()
    entries = []
    with path.open(encoding="utf-8") as file:
        for number, line in enumerate(file, 1):
            if not line.strip():
                continue
            try:
                row = validate_mapping(json.loads(line))
                if row["id"] in seen:
                    raise ValueError("duplicate id")
                seen.add(row["id"])
                entries.append(row)
            except (ValueError, TypeError) as exc:
                raise ValueError(f"{path}:{number}: {exc}") from exc
    if not entries:
        raise ValueError("empty mapping file")
    return entries


def query_for(row: dict) -> dict:
    """Optimistic concurrency: only unchanged, genuinely unattributed rows."""
    from bson import ObjectId
    return {
        "_id": ObjectId(row["id"]),
        "project_id": "ai26",
        "arena": "",
        "source.platform": row["platform"],
        "source_url": row["source_url"],
        "$or": [
            {"source.raw_ref": None},
            {"source.raw_ref": ""},
        ],
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--mongodb-uri", default=os.getenv("LACLAUGPT_MONGODB_URI"))
    parser.add_argument("--database", default="spectacleScraper")
    parser.add_argument("--collection", default="ai26__records")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="", help="Required literal: ai26-provenance-backfill")
    args = parser.parse_args(argv)
    if not args.mongodb_uri:
        parser.error("set LACLAUGPT_MONGODB_URI or --mongodb-uri")
    if args.apply and args.confirm != "ai26-provenance-backfill":
        parser.error("write requires --confirm ai26-provenance-backfill")
    if args.collection != "ai26__records":
        parser.error("refusing to modify a non-AI26 collection")
    rows = load_mappings(args.mapping)
    from pymongo import MongoClient
    client = MongoClient(args.mongodb_uri, serverSelectionTimeoutMS=5000)
    try:
        col = client[args.database][args.collection]
        counts = Counter()
        for row in rows:
            q = query_for(row)
            doc = col.find_one(q, {"_id": 1, "source_url": 1, "arena": 1,
                                   "source.platform": 1, "source.raw_ref": 1})
            if doc is None:
                counts["not_matching_guard"] += 1
                print(f"SKIP id={row['id']}: no matching unattributed rss/web document")
                continue
            counts["matched"] += 1
            print(f"{'APPLY' if args.apply else 'DRY-RUN'} id={row['id']} "
                  f"platform={row['platform']} arena={row['arena']} source={row['source_name']}")
            if args.apply:
                result = col.update_one(q, {"$set": {
                    "arena": row["arena"],
                    "source.raw_metadata.provenance_status": "legacy_reviewed_attribution",
                    "source.collector": "legacy_provenance_backfill",
                    "source.raw_metadata.source_name": row["source_name"],
                    "source.raw_metadata.arena": row["arena"],
                    "source.raw_metadata.provenance_backfill_evidence": row["evidence"],
                }})
                counts["updated"] += result.modified_count
        print(json.dumps({"mode": "apply" if args.apply else "dry-run", **counts}, sort_keys=True))
        return 0 if counts["not_matching_guard"] == 0 else 1
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
