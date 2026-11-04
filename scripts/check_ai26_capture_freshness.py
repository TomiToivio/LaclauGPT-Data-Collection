"""AI26 stratum freshness guard: monitor capture timestamps, not publication timestamps.

A platform holding half the corpus must not go quiet under a green ``status: ok``. This checks
*when we last captured* from a platform, which is a different question from when the material was
published: an archive can be perfectly fresh by publication date and weeks stale by capture date.

It reads MongoDB directly so it can be scheduled without a hand-maintained private file (#401):

    python3 scripts/check_ai26_capture_freshness.py --platforms x

``--captures-json`` remains supported for a deployment that keeps its own observations.

Exit status: 0 when every declared platform is fresh, 2 when one is missing or stale, 1 on a
usage/environment error. A monitor that cannot fail is not a monitor.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

#: Platforms whose silence must be visible. `x` is the one that motivated this script: the only
#: scheduled X path is a replay bridge over captures nothing produces (#401).
DEFAULT_PLATFORMS = ("x",)


def evaluate(
    captures: dict,
    *,
    now: datetime,
    max_age_hours: float = 24,
    platforms: tuple[str, ...] = DEFAULT_PLATFORMS,
) -> dict:
    from laclaugpt_data_collection.realtime import parse_source_time

    failures: dict[str, str] = {}
    observed: dict[str, dict] = {}
    for platform in platforms:
        raw = captures.get(platform)
        last = parse_source_time(raw) if raw else None
        if last is not None and last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        age = (now - last).total_seconds() / 3600 if last else None
        observed[platform] = {
            "latest_capture": last.isoformat() if last else None,
            "age_hours": round(age, 2) if age is not None else None,
        }
        if last is None:
            failures[platform] = "no_capture"
        elif age is not None and age < -1:
            failures[platform] = "future_capture_timestamp"
        elif age is not None and age > max_age_hours:
            failures[platform] = "stale_capture"
    return {"ok": not failures, "failures": failures, "observed": observed,
            "max_age_hours": max_age_hours, "checked_at": now.isoformat()}


def latest_captures_from_mongo(
    uri: str | None = None,
    *,
    database: str = "spectacleScraper",
    collection: str = "ai26__records",
    project: str = "ai26",
    platforms: tuple[str, ...] = DEFAULT_PLATFORMS,
) -> dict[str, str | None]:
    """Newest capture timestamp per platform, read from the records themselves.

    Capture provenance is a list on each record, and ``$max`` over the unwound list gives the most
    recent observation. Publication time is deliberately not used: a feed can publish this morning
    from a capture we made in September.
    """
    from pymongo import MongoClient

    uri = uri or os.environ.get("LACLAUGPT_MONGODB_URI")
    if not uri:
        raise RuntimeError("LACLAUGPT_MONGODB_URI is not set and no --mongo-uri was given")
    client = MongoClient(uri)
    try:
        rows = client[database][collection].aggregate([
            {"$match": {"project_id": project, "source.platform": {"$in": list(platforms)}}},
            {"$unwind": "$provenance"},
            {"$group": {"_id": "$source.platform",
                        "latest": {"$max": "$provenance.captured_at"}}},
        ])
        found = {str(r["_id"]): r.get("latest") for r in rows}
    finally:
        client.close()
    return {p: found.get(p) for p in platforms}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--captures-json", type=Path,
                        help="Optional private JSON mapping platforms to capture timestamps")
    parser.add_argument("--platforms", default=",".join(DEFAULT_PLATFORMS),
                        help="Comma-separated platforms that must be fresh (default: x)")
    parser.add_argument("--max-age-hours", type=float, default=24)
    parser.add_argument("--mongo-uri", default=None,
                        help="Defaults to $LACLAUGPT_MONGODB_URI")
    parser.add_argument("--database", default="spectacleScraper")
    parser.add_argument("--collection", default="ai26__records")
    parser.add_argument("--project", default="ai26")
    args = parser.parse_args()
    if args.max_age_hours <= 0:
        parser.error("max-age-hours must be positive")

    platforms = tuple(p.strip() for p in args.platforms.split(",") if p.strip())
    if not platforms:
        parser.error("at least one platform is required")

    try:
        if args.captures_json:
            captures = json.loads(args.captures_json.read_text(encoding="utf-8"))
        else:
            captures = latest_captures_from_mongo(
                args.mongo_uri, database=args.database, collection=args.collection,
                project=args.project, platforms=platforms)
    except Exception as exc:  # noqa: BLE001 - a monitor reports; it does not traceback
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, indent=2))
        return 1

    report = evaluate(captures, now=datetime.now(UTC),
                      max_age_hours=args.max_age_hours, platforms=platforms)
    print(json.dumps(report, indent=2))
    if not report["ok"]:
        stale = ", ".join(f"{k}={v}" for k, v in sorted(report["failures"].items()))
        print(f"STALE STRATUM: {stale}", file=sys.stderr)
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
