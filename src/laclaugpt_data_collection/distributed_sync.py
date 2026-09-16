"""Bounded bridge from Firefox local capture output to shared distributed backends.

This is deliberately boring: the browser keeps its localhost-only backend while a
small CLI/cron worker mirrors canonical JSONL records into MongoDB/S3/Redis. It is
a safe first distributed-test step and can later be replaced by direct event-driven
handoff without changing the storage contract.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .config import Settings
from .distributed_capture import DistributedCaptureSink


def _identity_token(collection_id: str, source_url: str) -> str:
    identity = f"{collection_id}\n{source_url}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def sync_normalized_records(
    settings: Settings,
    *,
    study_config: str | Path,
    data_root: Path,
    limit: int = 25,
) -> dict[str, Any]:
    """Mirror at most ``limit`` canonical JSONL records into distributed storage."""
    if limit < 1:
        raise ValueError("limit must be at least 1")
    normalized = data_root / "normalized"
    if not normalized.is_dir():
        raise ValueError(f"normalized capture directory does not exist: {normalized}")

    sink = DistributedCaptureSink(settings)
    sink.assert_private_config(study_config)

    scanned = 0
    synced = 0
    skipped = 0
    errors: list[str] = []
    for path in sorted(normalized.glob("*.jsonl")):
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if scanned >= limit:
                    break
                if not line.strip():
                    continue
                scanned += 1
                try:
                    record = json.loads(line)
                    source_url = str(record.get("source_url") or "")
                    if not source_url:
                        raise ValueError("record has no source_url")
                    collection_id = str(record.get("collection_id") or settings.project_id)
                    token = _identity_token(collection_id, source_url)
                    if not sink.redis.acquire_once(
                        f"distributed-sync:{settings.run_id}:{token}",
                        ttl_seconds=7 * 24 * 3600,
                    ):
                        skipped += 1
                        continue
                    sink.ingest(record)
                    synced += 1
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{path.name}:{line_number}: {str(exc)[:180]}")
            if scanned >= limit:
                break

    return {
        "status": "ok" if not errors else "partial",
        "project_id": settings.project_id,
        "run_id": settings.run_id,
        "scanned": scanned,
        "synced": synced,
        "skipped": skipped,
        "errors": errors,
    }
