#!/usr/bin/env python3
"""Read-only AI26 provenance candidate report for issue #250.

Does not infer an arena from author/text, and never modifies MongoDB.
Run twice and compare the SHA256 output before approving any separate repair.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tomllib
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit


def origin(url: str) -> tuple[str, str] | None:
    """Host + optional homepage path; never interpret article text as provenance."""
    if not isinstance(url, str) or not url.strip():
        return None
    parsed = urlsplit(url.strip())
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return None
    return parsed.hostname.lower().removeprefix("www."), parsed.path.rstrip("/")


def candidate_rows(manifest: dict, platform: str) -> list[dict]:
    kind = "feed" if platform == "rss" else "web_source"
    result = []
    for i, row in enumerate(manifest.get(kind, [])):
        arena = row.get("arena")
        if arena not in ("elites", "grassroots", "parliamentary"):
            continue
        # feed_url is the syndication endpoint, not necessarily the article host.
        endpoints = [row.get("homepage"), row.get("url")]
        if kind == "web_source":
            endpoints.append(row.get("page_url"))
        for endpoint in endpoints:
            parsed = origin(endpoint)
            if parsed:
                result.append({"kind": kind, "index": i, "name": row.get("name", ""),
                               "arena": arena, "origin": parsed, "url": endpoint})
    return result


def candidates(record: dict, manifest: dict) -> dict:
    platform = (record.get("source") or {}).get("platform")
    source = record.get("source") or {}
    # Only original source URLs; no author, fuzzy words, or publication-title guessing.
    urls = [source.get("url"), record.get("source_url"),
            (source.get("raw_metadata") or {}).get("source_url")]
    urls = [u for u in urls if origin(u)]
    matches = {}
    for url in urls:
        article = origin(url)
        for row in candidate_rows(manifest, platform):
            host, basepath = row["origin"]
            if article[0] != host:
                continue
            if basepath and not (article[1] == basepath or article[1].startswith(basepath + "/")):
                continue
            matches[(row["kind"], row["index"])] = row
    found = sorted(matches.values(), key=lambda r: (r["kind"], r["index"]))
    status = "unique" if len(found) == 1 else "ambiguous" if found else "unmatched"
    return {"id": str(record["_id"]), "platform": platform, "urls": urls,
            "status": status,
            "matches": [{"manifest_row": f'{r["kind"]}[{r["index"]}]',
                         "name": r["name"], "arena": r["arena"],
                         "matched_origin": r["url"]} for r in found]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mongodb-uri", default=os.environ.get("LACLAUGPT_MONGODB_URI"))
    parser.add_argument("--database", required=True, help="Explicit database name; never inferred")
    parser.add_argument("--manifest", type=Path, default=Path("data/config/ai26.sources.toml"))
    parser.add_argument("--output", type=Path, required=True, help="Private report destination")
    args = parser.parse_args()
    if not args.mongodb_uri:
        parser.error("--mongodb-uri or LACLAUGPT_MONGODB_URI is required")
    if args.output.exists():
        parser.error("output already exists; refuse overwriting an existing audit")
    manifest = tomllib.loads(args.manifest.read_text(encoding="utf-8"))
    from pymongo import MongoClient
    client = MongoClient(args.mongodb_uri, serverSelectionTimeoutMS=5000)
    collection = client[args.database]["ai26__records"]
    query = {"project_id": "ai26", "arena": {"$in": ["", None]},
             "source.platform": {"$in": ["rss", "web"]},
             "$and": [{"$or": [{"source.raw_ref": None}, {"source.raw_ref": ""}]},
                      {"$or": [{"source.collector": None}, {"source.collector": ""}]}]}
    records = list(collection.find(query))
    records.sort(key=lambda d: str(d["_id"]))
    report = [candidates(record, manifest) for record in records]
    status = dict(Counter(row["status"] for row in report))
    data = {"project": "ai26", "collection": "ai26__records",
            "scope": "missing-provenance rss/web only; deferred X excluded",
            "count": len(report), "status": status, "records": report}
    encoded = (json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    # Report deliberately does not contain credentials or article text.
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("xb") as target:
        target.write(encoded)
    args.output.chmod(0o600)
    print(f"READ ONLY: {len(report)} candidates; statuses={status}")
    print(f"report={args.output} sha256={hashlib.sha256(encoded).hexdigest()}")
    if len(report) != 59:
        print("WARNING: live scope differs from the 59 historical records; inspect before repairing")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
