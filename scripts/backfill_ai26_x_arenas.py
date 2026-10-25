"""Conservative AI26 X arena repair. Dry run by default; never guesses unknown actors.

Use only a study-config-declared X handle, never an LLM classification.
Production writes require --apply and --confirm, and are limited per invocation.
The original source fields and captured payload are never modified.
"""
from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

import yaml


def declared_x_handles(config: dict) -> dict[str, tuple[str, str]]:
    result: dict[str, tuple[str, str]] = {}
    for group in config.get("groups") or []:
        arena = str(group.get("arena") or "").strip()
        if not arena:
            continue
        for handle in (group.get("accounts") or {}).get("x") or []:
            key = str(handle).strip().lstrip("@").casefold()
            if not key:
                continue
            value = (arena, str(group.get("id") or "").strip())
            if key in result and result[key] != value:
                raise ValueError(f"ambiguous configured X handle: {key}")
            result[key] = value
    return result


def x_handle_from_profile(value: str) -> str:
    value = str(value or "").strip()
    if not value:
        return ""
    if value.startswith("@") and "/" not in value:
        return value[1:].casefold()
    if "://" not in value:
        return ""
    parsed = urlparse(value)
    if (parsed.hostname or "").lower() not in {"x.com", "www.x.com", "twitter.com", "www.twitter.com"}:
        return ""
    parts = [part for part in parsed.path.split("/") if part]
    if not parts or parts[0].lower() in {"i", "home", "search", "intent", "share"}:
        return ""
    if len(parts) > 1 and (len(parts) < 3 or parts[1].lower() != "status"):
        return ""
    return parts[0].lstrip("@").casefold()


def resolve_record(row: dict, mapping: dict[str, tuple[str, str]]) -> tuple[str, str] | None:
    src = row.get("source") or {}
    if str(src.get("platform") or "").lower() != "x":
        return None
    raw = src.get("raw_metadata") or {}
    # Prefer the declared capture target, falling back to the actual author only
    # when it is an exact known handle. Conflicting identities are not repaired.
    target = x_handle_from_profile(raw.get("source_platform_url") or "")
    author = x_handle_from_profile(str(src.get("author") or ""))
    if not author:
        author_text = str(src.get("author") or "").strip().lstrip("@").casefold()
        author = author_text if author_text in mapping else ""
    candidates = [x for x in (target, author) if x]
    if len(set(candidates)) > 1:
        return None
    key = candidates[0] if candidates else ""
    return mapping.get(key)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study-config", type=Path, required=True)
    parser.add_argument("--mongo-uri", default=os.environ.get("LACLAUGPT_MONGODB_URI", ""))
    parser.add_argument("--database", default=os.environ.get("LACLAUGPT_MONGODB_DATABASE", ""))
    parser.add_argument("--collection", default="ai26__records")
    parser.add_argument("--limit", type=int, default=20000)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="", help="required for writes: BACKFILL-AI26-X-ARENAS")
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("--limit must be positive")
    if not args.mongo_uri or not args.database:
        parser.error("provide --mongo-uri and --database (or corresponding environment variables)")
    if args.apply and args.confirm != "BACKFILL-AI26-X-ARENAS":
        parser.error("writes require --confirm BACKFILL-AI26-X-ARENAS")
    from pymongo import MongoClient

    mapping = declared_x_handles(yaml.safe_load(args.study_config.read_text(encoding="utf-8")) or {})
    client = MongoClient(args.mongo_uri, serverSelectionTimeoutMS=5000)
    collection = client[args.database][args.collection]
    query = {"project_id": "ai26", "source.platform": "x",
             "$or": [{"source.raw_metadata.arena": {"$exists": False}},
                     {"source.raw_metadata.arena": ""}, {"source.raw_metadata.arena": None}]}
    inspected = changed = eligible = 0
    outcomes = Counter()
    for row in collection.find(query, {"source": 1, "handoff": 1, "project_id": 1}).limit(args.limit):
        inspected += 1
        resolved = resolve_record(row, mapping)
        if resolved is None:
            outcomes["unresolved"] += 1
            continue
        arena, group_id = resolved
        eligible += 1
        outcomes[f"eligible:{arena}"] += 1
        if args.apply:
            updates = {"source.raw_metadata.arena": arena,
                       "source.raw_metadata.source_name": group_id}
            if (row.get("handoff") or {}).get("status") == "ready":
                updates["handoff.arena"] = arena
            # Compare-and-set: do not overwrite another worker's new arena.
            result = collection.update_one(
                {"_id": row["_id"], "project_id": "ai26",
                 "$or": [{"source.raw_metadata.arena": {"$exists": False}},
                         {"source.raw_metadata.arena": ""}, {"source.raw_metadata.arena": None}]},
                {"$set": updates},
            )
            changed += result.modified_count
    print(json.dumps({"mode": "apply" if args.apply else "dry-run", "inspected": inspected,
                      "eligible": eligible, "modified": changed,
                      "outcomes": dict(sorted(outcomes.items())),
                      "note": "Non-X records and unknown/conflicting handles are never modified"},
                     sort_keys=True))


if __name__ == "__main__":
    main()
