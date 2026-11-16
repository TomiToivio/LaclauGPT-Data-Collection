#!/usr/bin/env python3
"""Find AI26 records whose stored text is not text, and quarantine them (issue #429).

The fetcher now refuses such a body, but records collected before that guard are still in the store —
one of them is 43.8 % U+FFFD and is currently `ready`, so the analysis stage can read it as prose.
This finds them by the same plausibility rule the fetcher applies, and (with ``--apply``) marks them
excluded with a reason instead of deleting the evidence.

    python scripts/quarantine_implausible_text.py            # report only
    python scripts/quarantine_implausible_text.py --apply    # quarantine

Nothing is deleted: the text stays in the document, the provenance gains a marker, and
``handoff.status`` becomes ``excluded`` with ``handoff.reason`` naming the defect.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from typing import Any

from laclaugpt_data_collection.web_fetch import (
    MAX_CONTROL_CHARS,
    MAX_REPLACEMENT_SHARE,
    text_is_plausible,
)

QUARANTINE_REASON = "implausible_text:binary_body_rejected"


def diagnose(text: Any) -> tuple[bool, str, dict[str, Any]]:
    """The fetcher's own rule, applied to text already in the store."""
    value = text if isinstance(text, str) else ""
    replacements = value.count("\ufffd")
    control = sum(1 for character in value
                  if (ord(character) < 32 and character not in "\n\r\t") or ord(character) == 127)
    diagnostics = {
        "characters": len(value),
        "replacement_characters": replacements,
        "replacement_share": round(replacements / len(value), 4) if value else 0.0,
        "control_characters": control,
        "thresholds": {"replacement_share": MAX_REPLACEMENT_SHARE,
                       "control_characters": MAX_CONTROL_CHARS},
    }
    plausible, reason = text_is_plausible(diagnostics)
    return plausible, reason, diagnostics


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write the quarantine (default: report)")
    parser.add_argument("--project", default="ai26")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args(argv)

    from pymongo import MongoClient

    uri = os.environ.get("LACLAUGPT_MONGODB_URI")
    if not uri:
        parser.error("LACLAUGPT_MONGODB_URI is not set")
    database = os.environ.get("LACLAUGPT_MONGODB_DATABASE", "spectacleScraper")
    client = MongoClient(uri)
    collection = client[database][f"{args.project}__records"]

    suspects: list[dict[str, Any]] = []
    query = {"project_id": args.project}
    cursor = collection.find(query, {"content.text": 1, "handoff": 1, "source_url": 1})
    if args.limit:
        cursor = cursor.limit(args.limit)
    for document in cursor:
        text = (document.get("content") or {}).get("text") or ""
        if not text:
            continue
        plausible, reason, diagnostics = diagnose(text)
        if plausible:
            continue
        suspects.append({
            "record_id": str(document["_id"]),
            "source_url": document.get("source_url") or "",
            "handoff_status": (document.get("handoff") or {}).get("status") or "",
            "handoff_reason": (document.get("handoff") or {}).get("reason") or "",
            "reason": reason,
            "diagnostics": diagnostics,
        })

    print(json.dumps({"scanned_project": args.project, "suspects": len(suspects),
                      "records": suspects}, indent=2, ensure_ascii=False))
    if not args.apply or not suspects:
        if suspects and not args.apply:
            print("\nreport only; re-run with --apply to quarantine", flush=True)
        client.close()
        return 0

    stamped = datetime.now(UTC).isoformat()
    written = 0
    for suspect in suspects:
        # A record can be excluded for a reason that has nothing to do with its text — the one real
        # case was excluded for a missing publication time *and* holds mojibake. Replacing that
        # reason would hide a defect that still needs fixing, so the quarantine appends instead.
        existing = str(suspect.get("handoff_reason") or "").strip()
        reason = QUARANTINE_REASON if not existing or QUARANTINE_REASON in existing else (
            f"{existing};{QUARANTINE_REASON}")
        from bson import ObjectId

        key = ObjectId(suspect["record_id"]) if ObjectId.is_valid(suspect["record_id"]) else suspect["record_id"]
        collection.update_one(
            {"_id": key},
            {
                "$set": {
                    "handoff.status": "excluded",
                    "handoff.reason": reason,
                    "handoff.updated_at": stamped,
                },
                "$push": {
                    "provenance": {
                        "stage": "quarantine",
                        "module": "quarantine_implausible_text",
                        "captured_at": stamped,
                        "transformations": ["quarantine-implausible-text"],
                        "metadata": {
                            "reason": QUARANTINE_REASON,
                            "detail": suspect["reason"],
                            "diagnostics": suspect["diagnostics"],
                            "issue": "#429",
                        },
                    }
                },
            },
        )
        written += 1
    print(f"quarantined {written} of {len(suspects)} record(s)", flush=True)
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
