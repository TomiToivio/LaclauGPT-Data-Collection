"""Backfill the arena of AI26 records that lost it at capture (issue #336).

Read this before running.

## What this fixes

Before the capture fix in #345, the browser capture path discarded the study's own
actor->arena mapping, so 1,108 X records and 200 external-link children carried no
arena. 40% of the analysis-grade corpus could not enter the paper's arena
stratification. #345 stopped the leak; this fills what already leaked.

## Why both fields

`handoff.arena` is NOT recomputed on read. `handoff.routing_metadata()` derives it
from `source.raw_metadata.arena` when the envelope is *built*, so a record whose
raw_metadata is corrected but whose stored handoff is not will keep reporting a
blank arena to the analysis side. Both are written together.

## Safety

* **Dry run by default.** Nothing is written unless `--apply` is given.
* Every write is preceded by a rollback file recording the previous values.
* Only two fields are ever written: `source.raw_metadata.arena`,
  `source.raw_metadata.source_name`, and `handoff.arena` when it is blank.
* A record whose handle matches no configured group is **left blank and counted**.
  It is not guessed at: an invented arena is worse than a missing one, because it
  would silently enter a stratified sample as if it had been observed.

Usage::

    python scripts/backfill_ai26_arena.py --study-config data/config/ai26.yaml
    python scripts/backfill_ai26_arena.py --study-config data/config/ai26.yaml --apply
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import yaml  # noqa: E402

DEFAULT_COLLECTION = "ai26__records"


def handle_arena_map(study: dict) -> tuple[dict[str, dict[str, str]], int]:
    """Map casefolded X handle -> {arena, source_name} from the study config."""
    mapping: dict[str, dict[str, str]] = {}
    seen = 0
    for group in study.get("groups") or []:
        handles = (group.get("accounts") or group.get("handles") or {}).get("x") or []
        arena = str(group.get("arena") or "").strip()
        name = str(group.get("name") or group.get("id") or "").strip()
        for handle in handles:
            seen += 1
            key = str(handle).lstrip("@").casefold()
            if key and arena:
                mapping[key] = {"arena": arena, "source_name": name}
    return mapping, seen


def x_handle(*urls: str) -> str:
    """The last path segment of an x.com/twitter.com URL, casefolded."""
    for url in urls:
        if not url:
            continue
        try:
            host = (urlparse(url).hostname or "").casefold()
        except ValueError:
            continue
        if not host.endswith(("x.com", "twitter.com")):
            continue
        segments = [s for s in urlparse(url).path.split("/") if s]
        if segments:
            return segments[0].lstrip("@").casefold()
    return ""


def resolve(record: dict, mapping: dict[str, dict[str, str]]) -> tuple[str, str]:
    """Return (matched_handle, how) for one record, or ("", reason)."""
    source = record.get("source") or {}
    platform = str(source.get("platform") or "").casefold()

    if platform == "x":
        # The author IS the handle on X; the visited/API URL is the fallback.
        author = str(source.get("author") or "").lstrip("@").casefold()
        if author in mapping:
            return author, "author"
        handle = x_handle(str(source.get("parent_source_url") or ""))
        if handle in mapping:
            return handle, "parent_url"
        return "", "x_handle_not_in_study_config"

    if platform == "web":
        # An external-link child inherits the arena of the post that linked to it.
        for key in ("parent_source_url",):
            handle = x_handle(str(source.get(key) or ""))
            if handle in mapping:
                return handle, "parent_url"
        raw = source.get("raw_metadata") or {}
        for key in ("parent_source_url", "discovered_via", "original_link"):
            handle = x_handle(str(raw.get(key) or ""))
            if handle in mapping:
                return handle, f"raw_metadata.{key}"
        return "", "web_child_without_resolvable_parent"

    return "", f"platform_not_covered:{platform or 'blank'}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="backfill-ai26-arena")
    parser.add_argument("--study-config", required=True)
    parser.add_argument("--collection", default=DEFAULT_COLLECTION)
    parser.add_argument("--apply", action="store_true", help="write; default is a dry run")
    parser.add_argument("--rollback-out", default="")
    args = parser.parse_args(argv)

    study = yaml.safe_load(open(args.study_config, encoding="utf-8")) or {}
    mapping, handles_seen = handle_arena_map(study)
    if not mapping:
        print("error: the study config declares no X handles with an arena", file=sys.stderr)
        return 2

    from pymongo import MongoClient

    from laclaugpt_data_collection.config import Settings

    settings = Settings()
    db = MongoClient(settings.mongodb_uri)[settings.mongodb_database]
    collection = db[args.collection]

    query = {
        "project_id": settings.project_id,
        "$or": [
            {"source.raw_metadata.arena": {"$in": ["", None]}},
            {"source.raw_metadata.arena": {"$exists": False}},
        ],
    }

    counts = {"examined": 0, "filled": 0, "blank_left": 0, "already_had_arena": 0}
    by_platform: dict[str, int] = {}
    by_reason: dict[str, int] = {}
    updates: list[tuple[dict, dict, str]] = []

    for record in collection.find(query, {"source": 1, "handoff": 1, "source_url": 1}):
        counts["examined"] += 1
        source = record.get("source") or {}
        platform = str(source.get("platform") or "blank")
        by_platform[platform] = by_platform.get(platform, 0) + 1

        handle, how = resolve(record, mapping)
        if not handle:
            counts["blank_left"] += 1
            by_reason[how] = by_reason.get(how, 0) + 1
            continue

        target = mapping[handle]
        set_fields = {"source.raw_metadata.arena": target["arena"]}
        if target["source_name"]:
            set_fields["source.raw_metadata.source_name"] = target["source_name"]
        if not str((record.get("handoff") or {}).get("arena") or "").strip():
            set_fields["handoff.arena"] = target["arena"]

        previous = {
            "arena": (source.get("raw_metadata") or {}).get("arena"),
            "source_name": (source.get("raw_metadata") or {}).get("source_name"),
            "handoff_arena": (record.get("handoff") or {}).get("arena"),
        }
        updates.append(({"_id": record["_id"]}, set_fields, previous, how))
        by_reason[how] = by_reason.get(how, 0) + 1
        counts["filled"] += 1

    summary = {
        "mode": "apply" if args.apply else "dry-run",
        "collection": args.collection,
        "configured_x_handles_with_arena": len(mapping),
        "handles_seen": handles_seen,
        **counts,
        "by_platform": by_platform,
        "by_resolution": by_reason,
    }

    if args.apply and updates:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        rollback_path = Path(
            args.rollback_out
            or f"/mnt/workspace/LaclauGPT-Private/runtime/ai26/arena-backfill-rollback-{stamp}.json"
        )
        rollback_path.parent.mkdir(parents=True, exist_ok=True)
        rollback_path.write_text(
            json.dumps(
                [
                    {"id": str(flt["_id"]), "set": set_fields, "previous": previous, "via": how}
                    for flt, set_fields, previous, how in updates
                ],
                indent=1,
            ),
            encoding="utf-8",
        )
        summary["rollback_file"] = str(rollback_path)
        written = 0
        for flt, set_fields, _previous, _how in updates:
            written += collection.update_one(flt, {"$set": set_fields}).modified_count
        summary["documents_modified"] = written

    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
