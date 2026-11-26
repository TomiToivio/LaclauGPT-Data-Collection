"""Read-only, aggregate-only acceptance audit for AI26 issues #474 and #475."""
from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from typing import Any
from urllib.parse import urlsplit

from laclaugpt_data_collection.corpus_audit import record_source_name

_TARGETS = ("us_congressional_bills", "uk_ai_security_institute")
_X_HOSTS = {"x.com", "twitter.com", "www.x.com", "www.twitter.com", "mobile.x.com", "mobile.twitter.com"}
_OLD = "miri_ai"
_CORRECT = "miriberkeley"


def _x_handle(url: str) -> str:
    parts = urlsplit(url)
    segments = parts.path.strip("/").split("/")
    if parts.hostname in _X_HOSTS and len(segments) >= 3 and segments[1] == "status":
        return segments[0].casefold()
    return ""


def audit(records: Any, analysis: Any) -> dict[str, Any]:
    """Count candidate exclusions and deployed-source evidence without exposing rows."""
    old: Counter[str] = Counter()
    correct: Counter[str] = Counter()
    coverage = {name: Counter() for name in _TARGETS}
    miri_bluesky: Counter[str] = Counter()
    projection = {
        "source_url": 1, "source": 1, "source_name": 1, "arena": 1,
        "content.text": 1, "handoff.status": 1, "handoff.published_at": 1,
    }
    for record in records.find({"project_id": "ai26", "collection_id": "ai26"}, projection):
        source = record.get("source") or {}
        url = str(record.get("source_url") or "")
        platform = str(source.get("platform") or "").casefold()
        author = str(source.get("author") or "").strip().lstrip("@").casefold()
        handle = _x_handle(url)
        if handle in {_OLD, _CORRECT} or author in {_OLD, _CORRECT}:
            # Never infer an X identity from a conflicting author/platform.
            if ((platform in {"x", "twitter", ""} and handle in {_OLD, _CORRECT}
                 and author in {"", handle})
                or (platform in {"x", "twitter"} and author in {_OLD, _CORRECT}
                    and not handle)):
                bucket = old if (handle or author) == _OLD else correct
                bucket["records"] += 1
                bucket["arena_blank"] += not bool(record.get("arena"))
                bucket["ready"] += (record.get("handoff") or {}).get("status") == "ready"
                if url and analysis.count_documents({"source_url": url}):
                    bucket["with_analysis"] += 1
            else:
                old["ambiguous_identity"] += 1
        name = record_source_name(record)
        if name in coverage:
            bucket = coverage[name]
            bucket["records"] += 1
            bucket["parliamentary"] += record.get("arena") == "parliamentary"
            bucket["text"] += bool(str((record.get("content") or {}).get("text") or "").strip())
            bucket["dated"] += bool((record.get("handoff") or {}).get("published_at"))
            bucket["ready"] += (record.get("handoff") or {}).get("status") == "ready"
        if platform == "bluesky" and author == "intelligence.org":
            miri_bluesky["records"] += 1
            miri_bluesky["ready"] += (record.get("handoff") or {}).get("status") == "ready"
    def counts(bucket: Counter[str], keys: tuple[str, ...]) -> dict[str, int]:
        return {key: bucket[key] for key in keys}

    x_keys = ("records", "arena_blank", "ready", "with_analysis")
    return {
        "historical_wrong_miri": counts(old, (*x_keys, "ambiguous_identity")),
        "correct_miri_x": counts(correct, x_keys),
        "miri_bluesky": counts(miri_bluesky, ("records", "ready")),
        "parliamentary_sources": {
            name: counts(bucket, ("records", "parliamentary", "text", "dated", "ready"))
            for name, bucket in coverage.items()
        },
        "mode": "read_only",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    uri = os.environ.get("LACLAUGPT_MONGODB_URI")
    database = os.environ.get("LACLAUGPT_MONGODB_DATABASE")
    if not uri or not database:
        parser.error("configured AI26 MongoDB URI and database are required")
    try:
        from pymongo import MongoClient

        with MongoClient(uri, serverSelectionTimeoutMS=5000) as client:
            db = client[database]
            report = audit(db["ai26__records"], db["ai26__analysis_results"])
    except Exception as exc:
        print(json.dumps({"error": type(exc).__name__}))
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
