#!/usr/bin/env python3
"""Fill missing AI26 language labels from the text that is actually stored (#361).

The defect in #361 is a timing one: language is resolved while a record still holds a
feed excerpt (title + summary), so an article whose full text arrives later stays
labelled blank forever. Roughly 30% of the analysis-grade corpus is in that state, and
the gap is concentrated in the elites and parliamentary strata, which makes §4.2's
language stratification impossible to compute.

This tool does not guess. For every analysis-grade record with a blank language it
resolves the language from the stored content text, writes the result **with its
method and its previous value**, and skips the record when the text is too short or the
detector is not confident. Unknown stays unknown - a wrong label is worse than a blank
one, because a blank is visible and a wrong label is not.

Every written record carries:
    source.language                       the resolved tag
    source.raw_metadata.language_method   how it was obtained
    source.raw_metadata.language_backfill previous value, for reversibility

Dry-run by default. Never touches any field but those three.
"""
from __future__ import annotations

import argparse
import os
from typing import Any

ANALYSIS_FILTER = {"handoff.status": "ready", "handoff.published_at": {"$nin": ["", None]}}
BLANK_LANGUAGE = {"$in": ["", None]}
BATCH = 200


def _content_text(doc: dict[str, Any]) -> str:
    content = doc.get("content") or {}
    if isinstance(content, dict):
        return str(content.get("text") or "")
    return ""


def collection_name(project: str | None, explicit: str | None) -> str:
    """Records live in a project-namespaced collection (``ai26__records``).

    Assuming a bare ``records`` collection silently counted zero documents, which
    reads exactly like "the defect is fixed" - the most dangerous possible false
    negative for this tool.
    """
    if explicit:
        return explicit
    prefix = project or os.environ.get("LACLAUGPT_PROJECT_ID") or "ai26"
    return f"{prefix}__records"


def run(*, apply: bool, limit: int | None, database: str | None,
        project: str | None = None, collection: str | None = None) -> int:
    from pymongo import MongoClient

    from laclaugpt_data_collection.language import resolve_language

    uri = os.environ.get("LACLAUGPT_MONGODB_URI") or os.environ.get("LACLAUGPT_MONGO_URI")
    if not uri:
        raise SystemExit("set LACLAUGPT_MONGODB_URI (or LACLAUGPT_MONGO_URI)")
    db_name = database or os.environ.get("LACLAUGPT_MONGODB_DATABASE") or "laclaugpt"
    client = MongoClient(uri, serverSelectionTimeoutMS=15000)
    db = client[db_name]
    records = db[collection_name(project, collection)]
    print(f"collection: {records.name}")

    query = {**ANALYSIS_FILTER, "source.language": BLANK_LANGUAGE}
    # A limit of 0 is not "no limit" to the server: it raises Location15958 and the
    # whole run dies before writing anything. Counting with no limit argument is the
    # only correct way to ask for the full set.
    total = records.count_documents(query) if not limit else records.count_documents(query, limit=limit)
    print(f"blank-language analysis-grade records: {total}")

    resolved = skipped = 0
    by_method: dict[str, int] = {}
    cursor = records.find(query, {"content.text": 1, "source.language": 1}).batch_size(BATCH)
    if limit:
        cursor = cursor.limit(limit)

    updates: list[Any] = []
    for doc in cursor:
        text = _content_text(doc)
        tag, method = resolve_language(text)
        by_method[method] = by_method.get(method, 0) + 1
        if not tag:
            skipped += 1
            continue
        resolved += 1
        updates.append((doc["_id"], tag, method))

    print(f"resolved: {resolved} | still unknown: {skipped}")
    for method, count in sorted(by_method.items(), key=lambda item: -item[1]):
        print(f"  {method:22} {count}")

    if not apply:
        print("DRY RUN. Re-run with --apply to write.")
        return 0

    from pymongo import UpdateOne

    operations = [
        UpdateOne(
            {"_id": doc_id, "source.language": {"$in": ["", None]}},
            {"$set": {
                "source.language": tag,
                "source.raw_metadata.language_method": method,
                "source.raw_metadata.language_backfill": "",
            }},
        )
        for doc_id, tag, method in updates
    ]
    written = 0
    for start in range(0, len(operations), BATCH):
        result = records.bulk_write(operations[start:start + BATCH], ordered=False)
        written += result.modified_count
    print(f"written: {written}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write the resolved labels")
    parser.add_argument("--limit", type=int, default=None, help="inspect at most N records")
    parser.add_argument("--database", default=None)
    parser.add_argument("--project", default=None, help="project id, e.g. ai26")
    parser.add_argument("--collection", default=None, help="explicit collection name")
    args = parser.parse_args()
    return run(apply=args.apply, limit=args.limit, database=args.database,
               project=args.project, collection=args.collection)


if __name__ == "__main__":
    raise SystemExit(main())
