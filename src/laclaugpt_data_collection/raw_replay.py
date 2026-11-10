"""Replay raw captures that an exhausted object store deferred (#396).

``distributed_capture`` stopped discarding a record when the raw upload fails; it keeps the record
and marks ``raw_capture_pending`` on its provenance. That keeps the *data* (the payload is inside
the record) but leaves the archival object missing. Nothing was retrying it, so the marker could
outlive the outage by weeks without anyone noticing.

This pass finds those markers and uploads what was deferred. It is deliberately boring:

* it never invents a payload — a record with no ``raw_capture.payload`` is skipped and counted;
* a failure is classified, not raised: a store that is still full is reported as ``deferred``;
* the marker is removed only after the object is confirmed written;
* ``dry_run`` reports the backlog without touching the store.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable

PENDING_KEY = "raw_capture_pending"


def _encode(payload: Any) -> tuple[bytes, str]:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return encoded, hashlib.sha256(encoded).hexdigest()


def _run_id(doc: dict) -> str:
    for provenance in doc.get("provenance") or []:
        metadata = provenance.get("metadata") or {}
        run_id = metadata.get("run_id")
        if run_id:
            return str(run_id)
    return "replay"


def _clear_marker(provenance: Iterable[dict]) -> list[dict]:
    """Return the provenance list with the pending marker removed, leaving everything else intact."""
    cleaned = []
    for entry in provenance or []:
        entry = dict(entry)
        metadata = dict(entry.get("metadata") or {})
        metadata.pop(PENDING_KEY, None)
        entry["metadata"] = metadata
        cleaned.append(entry)
    return cleaned


def _mark_pending(provenance: Iterable[dict], reason: str) -> list[dict]:
    """Rewrite the marker with the current reason, leaving the rest of the provenance intact."""
    marked = []
    for entry in provenance or []:
        entry = dict(entry)
        metadata = dict(entry.get("metadata") or {})
        metadata[PENDING_KEY] = reason
        entry["metadata"] = metadata
        marked.append(entry)
    return marked


def replay_pending(
    records,
    objects,
    *,
    project_id: str = "ai26",
    limit: int = 100,
    dry_run: bool = False,
    classify_failure=None,
) -> dict:
    """Upload deferred raw captures. Returns counts, never raises for a *store* failure."""
    query = {
        "project_id": project_id,
        f'provenance.metadata.{PENDING_KEY}': {"$exists": True},
    }
    counts = {"examined": 0, "replayed": 0, "deferred": 0, "skipped_no_payload": 0,
              "errors": 0, "dry_run": dry_run}
    for doc in records.find(query).limit(limit):
        counts["examined"] += 1
        payload = ((doc.get("raw_capture") or {}).get("payload"))
        if payload is None:
            counts["skipped_no_payload"] += 1
            continue
        if dry_run:
            continue
        encoded, digest = _encode(payload)
        key = f"runs/{_run_id(doc)}/raw/{digest}.json"
        try:
            uri = objects.put_bytes(key, encoded, content_type="application/json")
        except Exception as exc:  # noqa: BLE001 - the caller decides what a failure means
            reason = (classify_failure or (lambda e: type(e).__name__))(exc)
            counts["deferred"] += 1
            records.update_one(
                {"_id": doc["_id"]},
                {"$set": {"provenance": _mark_pending(doc.get("provenance") or [], reason)}},
            )
            continue
        records.update_one(
            {"_id": doc["_id"]},
            {
                "$set": {
                    "raw_capture.ref": uri,
                    "raw_capture.checksum": f"sha256:{digest}",
                    "provenance": _clear_marker(doc.get("provenance") or []),
                }
            },
        )
        counts["replayed"] += 1
    return counts


def pending_count(records, *, project_id: str = "ai26") -> int:
    return int(records.count_documents({
        "project_id": project_id,
        f'provenance.metadata.{PENDING_KEY}': {"$exists": True},
    }))
