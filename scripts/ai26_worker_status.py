#!/usr/bin/env python3
"""Report AI26 worker/queue health from the shared MongoDB plane (#378).

Answers the operator questions without exposing payloads or credentials: which workers hold leases,
what is queued by source kind, how many leases have expired, and whether MongoDB is reachable at all.

Usage on Laskin:

    python scripts/ai26_worker_status.py --settings /path/to/laskin.env
    python scripts/ai26_worker_status.py --settings ... --json --capabilities non_browser

Exit codes: 0 healthy, 2 MongoDB not configured/unreachable (the caller can alert on this).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from laclaugpt_data_collection.config import Settings
from laclaugpt_data_collection.distributed import ProjectNamespace
from laclaugpt_data_collection.distributed_jobs import (
    BROWSER_REQUIRED_KINDS,
    LASKIN_CAPABILITIES,
    LOCALHOST_CAPABILITIES,
    JobLeaseStore,
)


def capability_set(name: str) -> frozenset[str]:
    return {
        "laskin": LASKIN_CAPABILITIES,
        "localhost": LOCALHOST_CAPABILITIES,
        "non_browser": LASKIN_CAPABILITIES,
        "all": LOCALHOST_CAPABILITIES,
    }[name]


def load_env_file(path: str | Path) -> None:
    """Read KEY=VALUE lines into the environment without echoing values."""
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().removeprefix("export ").strip()
        os.environ.setdefault(key, value.strip().strip("'\""))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--settings", help="env file with MongoDB settings (values are not printed)")
    ap.add_argument("--project-id", default="ai26")
    ap.add_argument(
        "--capabilities",
        default="localhost",
        choices=["laskin", "localhost", "non_browser", "all"],
        help="the capabilities this host declares; browser kinds are listed only when allowed",
    )
    ap.add_argument("--json", action="store_true", help="emit JSON instead of a text summary")
    args = ap.parse_args(argv)

    if args.settings:
        load_env_file(args.settings)

    settings = Settings()
    if not settings.mongodb_uri:
        print("error: MongoDB is not configured (no URI in settings)", file=sys.stderr)
        return 2

    from pymongo import MongoClient
    from pymongo.errors import PyMongoError

    namespace = ProjectNamespace(project_id=args.project_id)
    caps = capability_set(args.capabilities)
    try:
        client = MongoClient(
            settings.mongodb_uri,
            serverSelectionTimeoutMS=settings.mongodb_connect_timeout_ms,
            connect=False,
        )
        client.admin.command("ping")
        collection = client[settings.mongodb_database][namespace.mongo_collection("jobs")]
        store = JobLeaseStore(collection)
        status = store.status()
        reachable = True
    except PyMongoError as exc:
        status = {"error": type(exc).__name__}
        reachable = False

    report = {
        "reachable": reachable,
        "project_id": args.project_id,
        "database": settings.mongodb_database,
        "collection": namespace.mongo_collection("jobs"),
        "host_capabilities": sorted(caps),
        "browser_allowed": "browser" in caps,
        "browser_kinds_withheld": (
            [] if "browser" in caps else sorted(BROWSER_REQUIRED_KINDS)
        ),
        **status,
    }

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True, default=str))
    else:
        print(f"MongoDB: {'reachable' if reachable else 'UNREACHABLE'}")
        print(f"queue depth: {report.get('queue_depth', 0)}  {report.get('by_status', {})}")
        print(f"by kind: {report.get('by_kind', {})}")
        print(f"active leases: {report.get('active_leases', 0)}  expired: {report.get('expired_leases', 0)}")
        print(f"this host may take browser work: {'yes' if 'browser' in caps else 'no'}")
        for worker, entry in sorted(report.get("workers", {}).items()):
            print(f"  worker {worker}: running={entry['running']} kinds={entry['kinds']}")

    return 0 if reachable else 2


if __name__ == "__main__":
    raise SystemExit(main())
