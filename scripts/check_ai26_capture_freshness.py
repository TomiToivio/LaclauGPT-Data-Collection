"""AI26 stratum freshness guard: monitor capture timestamps, not publication timestamps.

Feed this with an authorized read-only export of capture observations.
Exit nonzero on missing/stale declared strata so scheduled jobs cannot report
an all-green cycle while an excluded browser source silently stops.
"""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
import os


def evaluate(captures: dict, *, now: datetime, max_age_hours: float = 24) -> dict:
    from laclaugpt_data_collection.realtime import parse_source_time
    failures = {}
    observed = {}
    for platform in ("x",):
        last = parse_source_time(captures.get(platform))
        age = (now - last).total_seconds() / 3600 if last else None
        observed[platform] = {"latest_capture": last.isoformat() if last else None,
                              "age_hours": round(age, 2) if age is not None else None}
        if last is None:
            failures[platform] = "no_capture"
        elif age > max_age_hours:
            failures[platform] = "stale_capture"
        elif age < -1:
            failures[platform] = "future_capture_timestamp"
    return {"ok": not failures, "failures": failures, "observed": observed}


def mongo_capture_observations(*, uri: str, database: str = "spectacleScraper",
                               collection: str = "ai26__records") -> dict:
    """Read actual X provenance; never substitute publication or job timestamps.

    No writes are performed. A missing collection, X stratum or timestamp is a
    failure for evaluate(), not a fabricated successful heartbeat.
    """
    from pymongo import MongoClient
    with MongoClient(uri, serverSelectionTimeoutMS=5000) as client:
        record = client[database][collection].find_one(
            {"project_id": "ai26", "source.platform": "x",
             "provenance.0.captured_at": {"$exists": True}},
            {"provenance.captured_at": 1},
            sort=[("provenance.0.captured_at", -1)],
        )
    provenance = (record or {}).get("provenance") or []
    return {"x": provenance[0].get("captured_at") if provenance else None}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sources = parser.add_mutually_exclusive_group(required=True)
    sources.add_argument("--captures-json", type=Path,
                        help="Private JSON mapping platforms to latest capture timestamps")
    sources.add_argument("--mongo", action="store_true",
                         help="Read X capture provenance from the AI26 Mongo store")
    parser.add_argument("--mongo-uri-env", default="LACLAUGPT_MONGODB_URI")
    parser.add_argument("--mongo-database", default="spectacleScraper")
    parser.add_argument("--max-age-hours", type=float, default=24)
    args = parser.parse_args()
    if args.max_age_hours <= 0:
        parser.error("max-age-hours must be positive")
    if args.mongo:
        uri = os.environ.get(args.mongo_uri_env)
        if not uri:
            print(json.dumps({"ok": False, "failures": {"x": "mongo_uri_missing"}}))
            return 2
        try:
            captures = mongo_capture_observations(uri=uri, database=args.mongo_database)
        except Exception as exc:
            # Never print credentials or connection URIs from driver exceptions.
            print(json.dumps({"ok": False, "failures": {"x": "mongo_query_failed"},
                              "error_type": type(exc).__name__}))
            return 2
    else:
        captures = json.loads(args.captures_json.read_text(encoding="utf-8"))
    report = evaluate(captures, now=datetime.now(UTC),
                      max_age_hours=args.max_age_hours)
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
