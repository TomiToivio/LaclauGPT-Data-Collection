"""Bounded, dry-run-first repair of AI26 X text-only handoff envelopes."""
from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping
from typing import Any

from laclaugpt_data_collection.handoff import build_handoff


def reconcile(collection: Any, *, limit: int, apply: bool = False) -> dict[str, int]:
    """Recompute waiting envelopes without changing source payloads or analysis."""
    if limit < 1:
        raise ValueError("limit must be positive")
    query = {
        "project_id": "ai26",
        "collection_id": "ai26",
        "source.platform": "x",
        "handoff.status": "waiting_media",
    }
    counts = {"scanned": 0, "eligible": 0, "updated": 0, "conflicts": 0}
    for record in collection.find(query).limit(limit):
        counts["scanned"] += 1
        previous = record["handoff"]
        envelope = build_handoff(record, project_id="ai26", run_id=previous.get("run_id", ""))
        if envelope["status"] != "ready" or envelope["reason"] != "ai26_x_text_only":
            continue
        counts["eligible"] += 1
        if apply:
            result = collection.update_one(
                {**query, "_id": record["_id"], "handoff.handoff_key": previous["handoff_key"]},
                {"$set": {"handoff": envelope}},
            )
            changed = int(result.modified_count)
            counts["updated"] += changed
            counts["conflicts"] += 1 - changed
    return counts


def main(env: Mapping[str, str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    settings = os.environ if env is None else env
    uri = settings.get("LACLAUGPT_MONGODB_URI")
    database = settings.get("LACLAUGPT_MONGODB_DATABASE")
    if not uri or not database or args.limit < 1:
        parser.error("explicit MongoDB URI, database and positive limit required")
    from pymongo import MongoClient

    try:
        with MongoClient(uri, serverSelectionTimeoutMS=5000) as client:
            counts = reconcile(client[database]["ai26__records"], limit=args.limit, apply=args.apply)
    except Exception as exc:
        # Driver exceptions may include private endpoint addresses.
        print(json.dumps({"error": type(exc).__name__}))
        return 1
    print(json.dumps({"apply": args.apply, **counts}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
