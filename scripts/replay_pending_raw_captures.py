"""Upload raw captures that an exhausted object store deferred (#396).

Run after the quota is raised, or on a schedule: it is idempotent and safe to repeat.

    python3 scripts/replay_pending_raw_captures.py --dry-run
    python3 scripts/replay_pending_raw_captures.py --limit 200

Environment: ``LACLAUGPT_MONGODB_URI`` and the usual ``LACLAUGPT_S3_*`` variables.
"""
from __future__ import annotations

import argparse
import json
import os

from laclaugpt_data_collection.config import Settings
from laclaugpt_data_collection.factory import build_object_store
from laclaugpt_data_collection.raw_replay import pending_count, replay_pending
from laclaugpt_data_collection.storage.remote import classify_object_store_failure


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--project", default="ai26")
    parser.add_argument("--database", default="spectacleScraper")
    parser.add_argument("--collection", default="ai26__records")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    uri = os.environ.get("LACLAUGPT_MONGODB_URI")
    if not uri:
        print(json.dumps({"ok": False, "error": "LACLAUGPT_MONGODB_URI is not set"}, indent=2))
        return 1

    from pymongo import MongoClient

    client = MongoClient(uri)
    try:
        records = client[args.database][args.collection]
        before = pending_count(records, project_id=args.project)
        objects = build_object_store(Settings())
        report = replay_pending(records, objects, project_id=args.project, limit=args.limit,
                                dry_run=args.dry_run,
                                classify_failure=classify_object_store_failure)
        report["pending_before"] = before
        report["pending_after"] = pending_count(records, project_id=args.project)
        print(json.dumps(report, indent=2))
        return 0 if report["errors"] == 0 else 2
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
