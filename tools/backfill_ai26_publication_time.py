# -*- coding: utf-8 -*-
"""Repair AI26 records that lost their source publication time (#295).

The ETUI feed emits ``Thu, 10/08/2026 - 13:30``. Neither ``fromisoformat`` nor
``parsedate_to_datetime`` accepted that shape, so those records were stored with
``handoff.published_at = null`` -- and because the study sets
``source_publication_time_required_for_analysis: true``, a null publication time made
them **permanently ineligible for analysis**. The parser fixes new records; this tool
repairs the ones already in the store.

Scope: ``ai26__records`` where ``handoff.published_at`` is empty **and**
``source.created_at`` parses with ``parse_source_time``. The second condition is what
keeps the tool honest: a record whose source really carries no date (the 12 one-off
web sources) is left excluded rather than given an invented time.

Safety:

* ``--dry-run`` is the default; nothing is written without ``--apply``.
* Before any write, every scanned document is dumped, full BSON, to
  ``data/backups/ai26_publication_time_backfill_<UTC>.json`` (``data/`` gitignored).
* Idempotent by construction: a repaired document has ``handoff.published_at`` set, so
  a second run finds nothing to repair.
* ``handoff`` is rebuilt with the collector's own ``build_handoff``, so the repaired
  envelope matches what the next resync would produce (revision included) and
  ``excluded``/missing-date becomes ``ready``/``source_ready`` for the same reason.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from laclaugpt_data_collection.handoff import build_handoff
from laclaugpt_data_collection.realtime import parse_source_time

REPO = Path(__file__).resolve().parents[1]
DEFAULT_BACKUP_DIR = REPO / "data" / "backups"
PROJECT_ID = "ai26"
BACKFILL_TAG = "#295"


def needs_repair(record: dict[str, Any]) -> bool:
    """Whether the record has a parseable source date that the handoff lost."""
    handoff = record.get("handoff") or {}
    if str(handoff.get("published_at") or "").strip():
        return False
    return parse_source_time((record.get("source") or {}).get("created_at")) is not None


def repair(record: dict[str, Any], *, project_id: str = PROJECT_ID) -> dict[str, Any] | None:
    """The ``$set`` fields for this record, or ``None`` when it needs nothing."""
    if not needs_repair(record):
        return None
    before = str((record.get("handoff") or {}).get("published_at") or "").strip()
    return {
        "handoff": build_handoff(
            record, project_id=project_id, run_id=str(record.get("run_id") or "")
        ),
        "source.backfill": BACKFILL_TAG,
        "source.raw_metadata.published_at_repaired": True,
        "source.raw_metadata.published_at_before": before,
    }


def summary(documents: list[dict[str, Any]], *, project_id: str = PROJECT_ID) -> dict[str, Any]:
    """Dry-run report: what would change, by source and by status transition."""
    by_source: dict[str, int] = {}
    statuses: dict[str, int] = {}
    repairable = 0
    for record in documents:
        fields = repair(record, project_id=project_id)
        if fields is None:
            continue
        repairable += 1
        raw = (record.get("source") or {}).get("raw_metadata") or {}
        name = str(raw.get("source_name") or "") or "(unnamed)"
        by_source[name] = by_source.get(name, 0) + 1
        transition = f"{str((record.get('handoff') or {}).get('status') or '(none)')} -> {fields['handoff']['status']}"
        statuses[transition] = statuses.get(transition, 0) + 1
    return {
        "scanned": len(documents),
        "repairable": repairable,
        "by_source": dict(sorted(by_source.items())),
        "status_changes": dict(sorted(statuses.items())),
    }


def _candidates(collection: Any, *, project_id: str, source: str = "") -> list[dict[str, Any]]:
    query: dict[str, Any] = {
        "project_id": project_id,
        "$or": [
            {"handoff.published_at": {"$in": [None, ""]}},
            {"handoff": {"$exists": False}},
        ],
    }
    if source:
        query["source.raw_metadata.source_name"] = source
    return list(collection.find(query))


def _write_backup(documents: list[dict[str, Any]], backup_dir: Path, timestamp: str) -> Path:
    from bson import json_util

    backup_dir.mkdir(parents=True, exist_ok=True)
    path = backup_dir / f"ai26_publication_time_backfill_{timestamp}.json"
    path.write_text(json_util.dumps(documents, indent=1), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write the repair (default: dry-run)")
    parser.add_argument("--mongodb-uri", default=os.environ.get("LACLAUGPT_MONGODB_URI"))
    parser.add_argument(
        "--mongodb-database",
        default=os.environ.get("LACLAUGPT_MONGODB_DATABASE", "spectacleScraper"),
    )
    parser.add_argument("--collection", default=f"{PROJECT_ID}__records")
    parser.add_argument("--project-id", default=PROJECT_ID)
    parser.add_argument("--source", default="", help="restrict to one source_name, e.g. etui")
    parser.add_argument("--backup-dir", type=Path, default=DEFAULT_BACKUP_DIR)
    args = parser.parse_args(argv)

    if not args.mongodb_uri:
        print("error: LACLAUGPT_MONGODB_URI (or --mongodb-uri) is required", file=sys.stderr)
        return 2
    from pymongo import MongoClient

    collection = MongoClient(args.mongodb_uri, serverSelectionTimeoutMS=5000)[args.mongodb_database][
        args.collection
    ]
    documents = _candidates(collection, project_id=args.project_id, source=args.source)
    report = summary(documents, project_id=args.project_id)

    print(f"scanned without a publication time: {report['scanned']}")
    print(f"repairable from source.created_at:  {report['repairable']}")
    print(f"by source: {report['by_source']}")
    print(f"status changes: {report['status_changes']}")
    if not args.apply:
        print("dry-run: nothing written. Re-run with --apply to repair.")
        return 0
    if not report["repairable"]:
        print("nothing to repair")
        return 0

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = _write_backup(documents, args.backup_dir, timestamp)
    print(f"backup written: {backup} ({len(documents)} documents)")

    written = failed = 0
    for record in documents:
        fields = repair(record, project_id=args.project_id)
        if fields is None:
            continue
        try:
            collection.update_one({"_id": record["_id"]}, {"$set": fields})
            written += 1
        except Exception as exc:  # noqa: BLE001 - report the document, keep going
            failed += 1
            print(f"  failed {record.get('source_url')}: {str(exc)[:160]}", file=sys.stderr)
    print(f"repaired: {written} document(s), {failed} failure(s)")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
