"""Audit and backfill cross-machine record identity (#478).

Three localhost collectors are supposed to write into the same `ai26__records`, which means the same post can
arrive from more than one machine, under more than one spelling of its URL, and more than once after a retry.
The store's uniqueness therefore has to be a *canonical identity*, not the string a browser happened to hold.

This module is the read-mostly half of that: it measures how a store is keyed today and can stamp the derived
identity onto documents that predate it. It never rewrites content, provenance or the captured URL.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from typing import Any, Iterable, Mapping
from urllib.parse import urlsplit

from .models import source_identity

__all__ = ["audit_documents", "backfill", "main"]


def _variants(url: str) -> dict[str, bool]:
    parts = urlsplit(url)
    return {
        "has_query": bool(parts.query),
        "trailing_slash": parts.path.endswith("/") and parts.path != "/",
        "non_canonical_host": parts.netloc.lower() != urlsplit(source_identity(url)).netloc.lower(),
        "scheme_is_http": parts.scheme.lower() == "http",
    }


def audit_documents(documents: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Report how a corpus is keyed, without echoing any record's URL.

    Counts only: hosts, variant flags, how many documents carry an identity, and how many share one. A
    duplicate here means two documents whose canonical identities are equal -- the exact condition a second
    writer would create if the store keyed on the raw URL.
    """
    total = 0
    hosts: Counter[str] = Counter()
    variants: Counter[str] = Counter()
    missing_identity = 0
    identities: Counter[str] = Counter()
    for document in documents:
        url = str(document.get("source_url") or "")
        if not url:
            continue
        total += 1
        hosts[urlsplit(url).netloc.lower()] += 1
        for name, present in _variants(url).items():
            if present:
                variants[name] += 1
        stored = document.get("source_identity")
        if not isinstance(stored, str) or not stored:
            missing_identity += 1
        identities[source_identity(url)] += 1
    duplicates = {identity: count for identity, count in identities.items() if count > 1}
    return {
        "documents": total,
        "distinct_identities": len(identities),
        "duplicate_identities": len(duplicates),
        "duplicate_documents": sum(count - 1 for count in duplicates.values()),
        "documents_without_identity": missing_identity,
        "variant_counts": dict(sorted(variants.items())),
        "hosts": dict(hosts.most_common(10)),
        "note": (
            "counts only; no URL or record content is printed. `documents_without_identity` counts documents "
            "written before the identity field existed — they still resolve, and `--backfill` stamps them."
        ),
    }


def backfill(collection: Any, project_id: str, *, write: bool) -> dict[str, Any]:
    """Stamp `source_identity` on documents that lack it; dry-run unless ``write`` is true."""
    scanned = written = 0
    for document in collection.find(
        {"project_id": project_id, "source_identity": {"$exists": False}},
        {"_id": 1, "source_url": 1},
    ):
        scanned += 1
        if not write:
            continue
        identity = source_identity(str(document.get("source_url") or ""))
        if not identity:
            continue
        collection.update_one({"_id": document["_id"]}, {"$set": {"source_identity": identity}})
        written += 1
    return {
        "project_id": project_id,
        "documents_missing_identity": scanned,
        "documents_updated": written,
        "applied": write,
        "note": "the captured URL is never modified; only the derived routing key is added",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mongodb-uri", required=True, help="connection string (never echoed)")
    parser.add_argument("--database", required=True)
    parser.add_argument("--collection", default="ai26__records")
    parser.add_argument("--project", default="ai26")
    parser.add_argument(
        "--backfill", action="store_true", help="write the identity onto legacy documents"
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        from pymongo import MongoClient
    except ImportError:  # pragma: no cover - optional dependency
        print("pymongo is not installed; install the [distributed] extra", file=sys.stderr)
        return 2

    client = MongoClient(args.mongodb_uri, serverSelectionTimeoutMS=5000)
    collection = client[args.database][args.collection]
    report = audit_documents(
        collection.find(
            {"project_id": args.project},
            {"source_url": 1, "source_identity": 1, "_id": 0},
        )
    )
    if args.backfill:
        report["backfill"] = backfill(collection, args.project, write=True)

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(
            f"documents {report['documents']} · distinct identities {report['distinct_identities']}"
        )
        print(
            f"duplicate identities {report['duplicate_identities']} "
            f"({report['duplicate_documents']} extra document(s)) · "
            f"without identity {report['documents_without_identity']}"
        )
        if report["variant_counts"]:
            print("variants:", report["variant_counts"])
        print("hosts:", report["hosts"])
        if "backfill" in report:
            print("backfill:", report["backfill"])
    # A clean audit and an audit that found duplicates both exit 0: this is a measurement, not a gate.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
