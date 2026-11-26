"""Find documents that are the same source twice (#478).

`canonicalize_source_url` now folds the X/Twitter host family and drops X share parameters, so *new* captures
of one post land on one identity. What that fix cannot do is tell anyone **what is already duplicated**: the
store was keyed on the raw URL for months, and the pairs written before it still exist. Repairing them means
choosing which document survives and what happens to anything already attached to it, which is a data
decision — so this module measures and lists, and never edits.

Output rules, because this runs against the research corpus:

* counts and identifiers only — never post text, author handles or full URLs;
* a duplicate group is described by the canonical identity's host, its numeric status id (X) or path (other
  hosts), the platforms involved and the stored `_id`s that a repair would have to choose between;
* nothing is written, and the exit status is a measurement, not a gate.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from typing import Any, Iterable, Mapping
from urllib.parse import urlsplit

from .models import canonicalize_source_url

__all__ = ["GROUP_SCHEMA", "audit_documents", "summarise_group"]

GROUP_SCHEMA = "laclaugpt.duplicates.v1"

_STATUS = re.compile(r"/status(?:es)?/(\d+)")


def _describe(identity: str) -> str:
    """A duplicate's name, without echoing the URL: host plus status id, or host plus path length."""
    parts = urlsplit(identity)
    status = _STATUS.search(parts.path)
    if status:
        return f"{parts.netloc}/status/{status.group(1)}"
    return f"{parts.netloc}/{len(parts.path.strip('/'))} path chars"


def summarise_group(identity: str, documents: list[Mapping[str, Any]]) -> dict[str, Any]:
    platforms = Counter(
        str((document.get("source") or {}).get("platform") or "") for document in documents
    )
    return {
        "identity": _describe(identity),
        "documents": len(documents),
        "document_ids": sorted(str(document.get("_id")) for document in documents),
        "platforms": dict(sorted(platforms.items())),
        "collection_methods": dict(
            sorted(
                Counter(
                    str((document.get("source") or {}).get("collection_method") or "")
                    for document in documents
                ).items()
            )
        ),
    }


def audit_documents(
    documents: Iterable[Mapping[str, Any]], *, show_groups: bool = False, limit: int = 20
) -> dict[str, Any]:
    """Group documents by canonical identity and report the groups that hold more than one."""
    total = 0
    groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for document in documents:
        url = str(document.get("source_url") or "")
        if not url:
            continue
        total += 1
        groups[canonicalize_source_url(url)].append(document)

    duplicates = {identity: docs for identity, docs in groups.items() if len(docs) > 1}
    report: dict[str, Any] = {
        "schema": GROUP_SCHEMA,
        "documents": total,
        "distinct_identities": len(groups),
        "duplicate_identities": len(duplicates),
        "duplicate_documents": sum(len(docs) - 1 for docs in duplicates.values()),
        "note": (
            "counts and identifiers only; no text, handles or full URLs. A repair has to choose which document "
            "survives and is therefore a data decision, not something this audit performs."
        ),
    }
    if show_groups and duplicates:
        ordered = sorted(duplicates.items(), key=lambda item: (-len(item[1]), item[0]))[:limit]
        report["groups"] = [summarise_group(identity, docs) for identity, docs in ordered]
        report["groups_shown"] = len(ordered)
        report["groups_total"] = len(duplicates)
    return report


def audit_collection(
    collection: Any, project_id: str, *, show_groups: bool, limit: int
) -> dict[str, Any]:
    projection = {"source_url": 1, "source.platform": 1, "source.collection_method": 1}
    return audit_documents(
        collection.find({"project_id": project_id}, projection),
        show_groups=show_groups,
        limit=limit,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mongodb-uri", required=True, help="connection string (never echoed)")
    parser.add_argument("--database", required=True)
    parser.add_argument("--collection", default="ai26__records")
    parser.add_argument("--project", default="ai26")
    parser.add_argument(
        "--show-groups", action="store_true", help="list duplicate groups (ids only)"
    )
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        from pymongo import MongoClient
    except ImportError:  # pragma: no cover - optional dependency
        print("pymongo is not installed; install the [distributed] extra", file=sys.stderr)
        return 2

    collection = MongoClient(args.mongodb_uri, serverSelectionTimeoutMS=5000)[args.database][
        args.collection
    ]
    report = audit_collection(
        collection, args.project, show_groups=args.show_groups, limit=args.limit
    )

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    print(
        f"{report['documents']} documents · {report['distinct_identities']} distinct identities · "
        f"{report['duplicate_identities']} duplicate identit(ies) "
        f"({report['duplicate_documents']} extra document(s))"
    )
    for group in report.get("groups", []):
        print(
            f"  {group['identity']}: {group['documents']} docs {group['document_ids']} "
            f"platforms={group['platforms']}"
        )
    if report.get("groups_total", 0) > report.get("groups_shown", 0):
        print(f"  … {report['groups_total'] - report['groups_shown']} more group(s); raise --limit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
