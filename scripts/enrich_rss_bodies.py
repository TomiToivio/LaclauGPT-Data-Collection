#!/usr/bin/env python3
"""Enrich headline-only RSS records by fetching the article body (#416).

Read-only unless `--apply` is given. Selection is bounded (`--limit`) and ordered worst-first, so a
run always repairs the most unusable records before anything else and can be stopped at any point.

    python scripts/enrich_rss_bodies.py --dry-run --limit 20
    python scripts/enrich_rss_bodies.py --apply --limit 50 --source tech_policy_press

Every applied record keeps its identity and gains a provenance entry naming the fetch
(`transformations: ["rss-body-enrichment"]`), so "where did this text come from?" is answerable per
record and a second run cannot double-enrich.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from laclaugpt_data_collection.rss_body_enrichment import (  # noqa: E402
    SHORT_TEXT_CHARS,
    enrich_record,
    select_records,
    summarise,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="enrich-rss-bodies", description=__doc__)
    parser.add_argument("--mongodb-uri", default=os.environ.get("LACLAUGPT_MONGODB_URI"))
    parser.add_argument("--database", default=os.environ.get("LACLAUGPT_MONGODB_DATABASE", "spectacleScraper"))
    parser.add_argument("--collection", default="ai26__records")
    parser.add_argument("--project", default="ai26")
    parser.add_argument("--source", default=None, help="restrict to one raw_metadata.source_name")
    parser.add_argument("--max-chars", type=int, default=SHORT_TEXT_CHARS)
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--apply", action="store_true", help="write the patches (default: dry run)")
    parser.add_argument("--json", default=None, help="write the run summary here")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    if not args.mongodb_uri:
        print("--mongodb-uri or LACLAUGPT_MONGODB_URI is required", file=sys.stderr)
        return 2

    from pymongo import MongoClient

    from laclaugpt_data_collection.web_fetch import fetch_html_page

    client = MongoClient(args.mongodb_uri)
    collection = client[args.database][args.collection]
    query: dict[str, object] = {
        "project_id": args.project,
        "handoff.status": "ready",
        "source.platform": {"$in": ["rss", "atom"]},
    }
    if args.source:
        query["source.raw_metadata.source_name"] = args.source
    projection = {
        "_id": 1,
        "project_id": 1,
        "source_url": 1,
        "handoff.status": 1,
        "source.platform": 1,
        "source.language": 1,  # do not overwrite declared language tags
        "source.raw_metadata.source_name": 1,
        "content.text": 1,
        "human_readable": 1,
        "provenance": 1,
    }
    documents = list(collection.find(query, projection))
    candidates = select_records(documents, limit=args.limit, max_chars=args.max_chars)
    print(
        f"candidates: {len(candidates)} of {len(documents)} ready rss records "
        f"(< {args.max_chars} chars, not yet enriched)",
        file=sys.stderr,
    )

    results = []
    applied = 0
    for document in candidates:
        result, patch = enrich_record(document, fetch=fetch_html_page, max_chars=args.max_chars)
        results.append(result)
        source_name = (document.get("source") or {}).get("raw_metadata", {}).get("source_name", "")
        print(
            f"  {result.status:9} {result.chars_before:>6} -> {result.chars_after:>7} chars  "
            f"[{source_name}] {result.url[:90]} {result.detail}",
            file=sys.stderr,
        )
        if patch and args.apply:
            collection.update_one({"_id": document["_id"]}, {"$set": patch})
            applied += 1

    summary = summarise(results)
    summary["applied"] = applied
    summary["dry_run"] = not args.apply
    if args.json:
        Path(args.json).write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k not in {"enriched", "failures", "skipped"}}, indent=2))
    client.close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
