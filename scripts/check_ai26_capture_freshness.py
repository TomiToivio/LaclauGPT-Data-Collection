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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--captures-json", required=True, type=Path,
                        help="Private JSON mapping platforms to latest capture timestamps")
    parser.add_argument("--max-age-hours", type=float, default=24)
    args = parser.parse_args()
    if args.max_age_hours <= 0:
        parser.error("max-age-hours must be positive")
    report = evaluate(json.loads(args.captures_json.read_text(encoding="utf-8")),
                      now=datetime.now(UTC), max_age_hours=args.max_age_hours)
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
