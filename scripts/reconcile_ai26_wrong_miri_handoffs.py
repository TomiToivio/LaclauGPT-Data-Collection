"""Dry-run-first correction of AI26 handoff status for the proven wrong MIRI account."""
from __future__ import annotations

import argparse
import json
import os
from typing import Any

from laclaugpt_data_collection.ai26_source_frame import (
    MIRI_WRONG_ACCOUNT_REASON,
    is_wrong_miri_account,
)
from laclaugpt_data_collection.handoff import build_handoff


def reconcile(records: Any, analysis: Any, *, apply: bool = False) -> dict[str, int]:
    """Only change handoff status/reason; never remove source or analysis records."""
    counts = {"confirmed": 0, "already_excluded": 0, "with_analysis": 0,
              "eligible": 0, "updated": 0, "conflicts": 0}
    query = {"project_id": "ai26", "collection_id": "ai26"}
    for record in records.find(query):
        if not is_wrong_miri_account(record):
            continue
        counts["confirmed"] += 1
        previous = record.get("handoff") or {}
        if previous.get("status") == "excluded" and previous.get("reason") == MIRI_WRONG_ACCOUNT_REASON:
            counts["already_excluded"] += 1
            continue
        # An existing result needs a separate downstream review, not automatic mutation.
        if analysis.count_documents({"source_url": record["source_url"]}):
            counts["with_analysis"] += 1
            continue
        if not previous.get("handoff_key"):
            counts["conflicts"] += 1
            continue
        expected = build_handoff(record, project_id="ai26")
        if expected["reason"] != MIRI_WRONG_ACCOUNT_REASON:
            counts["conflicts"] += 1
            continue
        counts["eligible"] += 1
        if apply:
            updated = records.update_one(
                {**query, "_id": record["_id"], "handoff": previous,
                 "source_url": record["source_url"], "source": record.get("source")},
                {"$set": {"handoff.status": "excluded", "handoff.reason": MIRI_WRONG_ACCOUNT_REASON}},
            )
            counts["updated"] += int(updated.modified_count)
            counts["conflicts"] += 1 - int(updated.modified_count)
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Apply only after reviewing dry run")
    args = parser.parse_args(argv)
    uri = os.environ.get("LACLAUGPT_MONGODB_URI")
    database = os.environ.get("LACLAUGPT_MONGODB_DATABASE")
    if not uri or not database:
        parser.error("configured AI26 MongoDB URI and database are required")
    try:
        from pymongo import MongoClient

        with MongoClient(uri, serverSelectionTimeoutMS=5000) as client:
            db = client[database]
            counts = reconcile(db["ai26__records"], db["ai26__analysis_results"], apply=args.apply)
    except Exception as exc:
        print(json.dumps({"error": type(exc).__name__}))
        return 1
    print(json.dumps({"apply": args.apply, **counts}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
