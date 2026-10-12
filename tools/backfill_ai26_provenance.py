# -*- coding: utf-8 -*-
"""One-time provenance backfill for the AI26 store (issue #250).

The corpus holds records with `arena == ""` and no source provenance
(`source.raw_ref` null, `source.collector` "") that were ingested before those
fields were populated. This tool recovers the originating manifest row for each
such record and writes back the provenance -- and, where the row declares an
arena, the arena -- so the arena shares are computed on the whole corpus rather
than 95% of it.

Scope: ``ai26__records`` with ``project_id == "ai26"``, ``arena == ""`` and
``source.platform`` in {``rss``, ``web``} -- 55 rss + 4 web = 59 records. The
55 blank-arena ``x`` records are the documented 2026-09-16 stage-deferred
capture (#207) and are deliberately out of scope.

Safety:

* ``--dry-run`` is the default; nothing is written without ``--apply``.
* Before any write, every affected document is dumped, full BSON, to
  ``data/backups/ai26_provenance_backfill_<UTC>.json`` (``data/`` is gitignored).
* The operation is idempotent: a record already carrying ``source.backfill =
  "#250"`` is never rewritten, so a second ``--apply`` changes nothing.
* No arena is ever guessed: a record whose manifest row declares no arena, or
  whose row cannot be resolved at all, keeps ``arena == ""``.
"""
from __future__ import annotations

import argparse
import os
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bson import json_util
from pymongo import MongoClient

REPO = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = REPO / "configs" / "studies" / "ai26.sources.example.toml"
DEFAULT_BACKUP_DIR = REPO / "data" / "backups"

PROJECT_ID = "ai26"
COLLECTION = "ai26__records"
BACKFILL_TAG = "#250"
UNATTRIBUTED_REASON = "#250: no recoverable manifest row; pre-provenance ingestion"

# Expected scope of the one-time backfill, asserted on the unrun store.
EXPECTED_TOTAL = 59
EXPECTED_BY_PLATFORM = {"rss": 55, "web": 4}

# Manifest table -> platform, and -> the collector that produces it.
TABLE_PLATFORM = {
    "feed": "rss",
    "web_source": "web",
    "x_account": "x",
    "bluesky_account": "bluesky",
    "mastodon_account": "mastodon",
    "youtube_source": "youtube",
    "scholarly_query": "scholarly",
}
TABLE_COLLECTOR = {
    "feed": "rss-feedparser",
    "web_source": "external-link-fetcher",
    "x_account": "x-browser-capture",
    "bluesky_account": "bluesky-api",
    "mastodon_account": "mastodon-api",
    "youtube_source": "youtube-transcript",
    "scholarly_query": "arxiv",
}


def _norm_url(url: Any) -> str:
    if not isinstance(url, str):
        return ""
    return url.strip().rstrip("/")


def load_manifest_rows(path: Path) -> list[dict[str, Any]]:
    """Every manifest row as a flat dict with its table, platform and URLs."""
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    for table, platform in TABLE_PLATFORM.items():
        for row in data.get(table) or []:
            if not isinstance(row, dict):
                continue
            rows.append(
                {
                    "table": table,
                    "platform": platform,
                    "name": str(row.get("name") or "").strip(),
                    "arena": str(row.get("arena") or "").strip(),
                    "feed_url": str(row.get("feed_url") or "").strip(),
                    "homepage": str(row.get("homepage") or "").strip(),
                    "collector": TABLE_COLLECTOR.get(table, platform),
                }
            )
    return rows


def _row_reference(row: dict[str, Any]) -> str:
    return f"ai26.sources.example.toml#{row['table']}:{row['name']}"


def _document_signals(doc: dict[str, Any]) -> dict[str, Any]:
    src = doc.get("source") or {}
    raw_meta = src.get("raw_metadata") or {}
    provenance = doc.get("provenance") or []
    last = provenance[-1] if provenance else {}
    prov_meta = last.get("metadata") or {}
    payload = (doc.get("raw_capture") or {}).get("payload") or {}
    title_detail = payload.get("title_detail") if isinstance(payload, dict) else None
    base = title_detail.get("base") if isinstance(title_detail, dict) else None
    return {
        "platform": str(src.get("platform") or ""),
        "source_name": str(raw_meta.get("source_name") or prov_meta.get("source_name") or "").strip(),
        "author": str(src.get("author") or "").strip(),
        "urls": [
            _norm_url(u)
            for u in (
                last.get("visited_url"),
                last.get("api_url"),
                doc.get("source_url"),
                base,
            )
            if u
        ],
    }


def resolve_row(rows: list[dict[str, Any]], signals: dict[str, Any]) -> tuple[dict[str, Any] | None, str, str]:
    """Resolve a document to its manifest row.

    Returns (row or None, confidence, human-readable reason). Confidence is
    ``high`` when the recorded source name matches and the URL corroborates it,
    ``medium`` when only the name or only the URL resolves, ``none`` when
    nothing resolves.
    """
    by_name = {row["name"]: row for row in rows if row["name"]}
    by_url: dict[str, dict[str, Any]] = {}
    for row in rows:
        for url in (row["feed_url"], row["homepage"]):
            if _norm_url(url):
                by_url.setdefault(_norm_url(url), row)

    name = signals["source_name"]
    urls = signals["urls"]

    if name and name in by_name:
        row = by_name[name]
        row_urls = {_norm_url(row["feed_url"]), _norm_url(row["homepage"])} - {""}
        if row_urls & set(urls):
            return row, "high", f"source_name={name!r}; url corroborates the row"
        return row, "medium", f"source_name={name!r}; no url corroboration"

    for url in urls:
        if url in by_url:
            row = by_url[url]
            return row, "medium", f"url {url!r} matches manifest row {row['name']!r}"

    return None, "none", "no manifest row matches the name or url"


def _select_targets(col: Any) -> list[dict[str, Any]]:
    query = {
        "project_id": PROJECT_ID,
        "arena": "",
        "source.platform": {"$in": ["rss", "web"]},
        "source.backfill": {"$ne": BACKFILL_TAG},
    }
    return list(col.find(query))


def _already_backfilled(col: Any) -> int:
    return int(col.count_documents({"project_id": PROJECT_ID, "source.backfill": BACKFILL_TAG}))


def build_plan(col: Any, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A per-document plan: the resolved row, confidence and the intended write."""
    plan: list[dict[str, Any]] = []
    for doc in _select_targets(col):
        signals = _document_signals(doc)
        row, confidence, reason = resolve_row(rows, signals)
        arena = row["arena"] if row and row["arena"] else ""
        plan.append(
            {
                "id": doc.get("_id"),
                "platform": signals["platform"],
                "author": signals["author"],
                "url": doc.get("source_url"),
                "row": row,
                "confidence": confidence,
                "reason": reason,
                "arena": arena,
                "attributable": row is not None,
            }
        )
    return plan


def _print_plan(plan: list[dict[str, Any]]) -> None:
    for entry in plan:
        row_name = entry["row"]["name"] if entry["row"] else "-"
        print(
            f"[{entry['confidence']:>6}] platform={entry['platform']:<3} "
            f"row={row_name:<24} arena={entry['arena'] or '(none)':<13} "
            f"author={entry['author'][:18]:<18} url={str(entry['url'])[:70]}"
        )


def _summarize(plan: list[dict[str, Any]]) -> dict[str, int]:
    to_arena = [e for e in plan if e["attributable"] and e["arena"]]
    arena_less = [e for e in plan if e["attributable"] and not e["arena"]]
    unattributed = [e for e in plan if not e["attributable"]]
    return {
        "total": len(plan),
        "rss": sum(1 for e in plan if e["platform"] == "rss"),
        "web": sum(1 for e in plan if e["platform"] == "web"),
        "resolved_to_arena": len(to_arena),
        "resolved_arena_less": len(arena_less),
        "resolved_total": len(to_arena) + len(arena_less),
        "unattributed": len(unattributed),
    }


def _write_backup(col: Any, backup_dir: Path, timestamp: str) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    path = backup_dir / f"ai26_provenance_backfill_{timestamp}.json"
    docs = _select_targets(col)
    path.write_text(json_util.dumps(docs, indent=1), encoding="utf-8")
    return path


def apply_backfill(col: Any, plan: list[dict[str, Any]], timestamp: str) -> dict[str, int]:
    matched = 0
    modified = 0
    for entry in plan:
        set_fields: dict[str, Any] = {
            "source.backfill": BACKFILL_TAG,
            "source.backfilled_at": timestamp,
        }
        if entry["attributable"]:
            set_fields["source.raw_ref"] = _row_reference(entry["row"])
            set_fields["source.collector"] = entry["row"]["collector"]
            if entry["arena"]:
                set_fields["arena"] = entry["arena"]
                set_fields["source.raw_metadata.arena"] = entry["arena"]
        else:
            set_fields["source.unattributed"] = True
            set_fields["source.unattributed_reason"] = UNATTRIBUTED_REASON
        result = col.update_one({"_id": entry["id"]}, {"$set": set_fields})
        matched += int(result.matched_count)
        modified += int(result.modified_count)
    return {"matched": matched, "modified": modified}


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="backfill-ai26-provenance", description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write the backfill (default: dry-run)")
    parser.add_argument("--mongodb-uri", default=os.environ.get("LACLAUGPT_MONGODB_URI"))
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--backup-dir", type=Path, default=DEFAULT_BACKUP_DIR)
    args = parser.parse_args(argv)

    if not args.mongodb_uri:
        print("error: --mongodb-uri or LACLAUGPT_MONGODB_URI is required", file=sys.stderr)
        return 2

    rows = load_manifest_rows(args.manifest)
    client = MongoClient(args.mongodb_uri)
    col = client.get_default_database()[COLLECTION]

    plan = build_plan(col, rows)
    summary = _summarize(plan)
    applied = _already_backfilled(col)

    _print_plan(plan)
    print("-" * 100)
    print(f"pending (not yet backfilled): {summary['total']} "
          f"(rss {summary['rss']}, web {summary['web']})")
    print(f"resolved to a manifest row: {summary['resolved_total']} "
          f"(of which arena assigned: {summary['resolved_to_arena']}, "
          f"row declares no arena: {summary['resolved_arena_less']})")
    print(f"unattributed (no recoverable row): {summary['unattributed']}")
    print(f"records already carrying source.backfill={BACKFILL_TAG!r}: {applied}")

    if applied == 0:
        assert summary["total"] == EXPECTED_TOTAL, (
            f"expected {EXPECTED_TOTAL} target documents, found {summary['total']}"
        )
        assert summary["rss"] == EXPECTED_BY_PLATFORM["rss"], summary
        assert summary["web"] == EXPECTED_BY_PLATFORM["web"], summary
    else:
        assert summary["total"] == 0, (
            f"idempotency broken: {summary['total']} documents still pending after apply"
        )

    if not args.apply:
        print("dry-run: no writes performed (pass --apply to write)")
        return 0

    timestamp = _now_stamp()
    backup = _write_backup(col, args.backup_dir, timestamp)
    print(f"backup written: {backup} (full BSON of {summary['total']} documents)")
    result = apply_backfill(col, plan, timestamp)
    print(f"apply complete: matched={result['matched']} modified={result['modified']} "
          f"timestamp={timestamp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
