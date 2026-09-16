"""Cron-friendly local Collection -> Analysis handoff exporter."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .handoff import build_handoff, ready_sort_key, routing_metadata
from .store import CollectionStore


def load_records(data_root: str | Path) -> list[dict[str, Any]]:
    root = Path(data_root)
    records: list[dict[str, Any]] = []
    for path in sorted((root / "normalized").glob("*.jsonl")):
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    value = json.loads(line)
                    if isinstance(value, dict):
                        records.append(value)
    return records


def export_handoffs(
    data_root: str | Path,
    *,
    project_id: str = "",
    run_id: str = "",
    collection_id: str | None = None,
    limit: int = 100,
    ready_only: bool = True,
) -> list[dict[str, Any]]:
    """Return deterministic handoff envelopes suitable for a polling Analysis worker."""
    if limit < 1:
        raise ValueError("limit must be at least 1")
    store = CollectionStore(data_root)
    try:
        envelopes: list[dict[str, Any]] = []
        for record in load_records(data_root):
            routed_collection, _ = routing_metadata(
                record,
                default_collection=project_id or "default",
            )
            if collection_id and routed_collection != collection_id:
                continue
            source_url = str(record.get("source_url") or "")
            states = store.media_states(source_url, collection_id=routed_collection)
            envelope = build_handoff(
                record,
                project_id=project_id,
                run_id=run_id,
                media_states=states,
            )
            if ready_only and envelope["status"] != "ready":
                continue
            envelopes.append(envelope)
        envelopes.sort(key=ready_sort_key)
        return envelopes[:limit]
    finally:
        store.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="laclaugpt-handoff")
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--project-id", default="")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--collection-id")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument(
        "--include-not-ready",
        action="store_true",
        help="include waiting/excluded records for diagnostics",
    )
    args = parser.parse_args(argv)
    envelopes = export_handoffs(
        args.data_root,
        project_id=args.project_id,
        run_id=args.run_id,
        collection_id=args.collection_id,
        limit=args.limit,
        ready_only=not args.include_not_ready,
    )
    for envelope in envelopes:
        print(json.dumps(envelope, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
