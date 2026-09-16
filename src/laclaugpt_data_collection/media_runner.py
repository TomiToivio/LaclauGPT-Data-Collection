"""Cron-friendly runner for pending multimodal media downloads."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .media import MediaDownloader
from .store import CollectionStore


def load_records(data_root: str | Path) -> list[dict]:
    """Load canonical JSONL records produced by any collector."""
    root = Path(data_root)
    records: list[dict] = []
    for path in sorted((root / "normalized").glob("*.jsonl")):
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    records.append(json.loads(line))
    return records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="laclaugpt-media-download")
    parser.add_argument("--data-root", required=True, help="persistent collection data root")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args(argv)

    store = CollectionStore(args.data_root)
    try:
        downloader = MediaDownloader(store, workers=args.workers)
        jobs = downloader.enqueue_from_records(load_records(args.data_root))
        results = downloader.run_queue(jobs)
        completed = sum(row.get("status") == "completed" for row in results)
        failed = sum(row.get("status") == "failed" for row in results)
        print(json.dumps({"queued": len(jobs), "completed": completed, "failed": failed}))
        return 0 if failed == 0 else 1
    finally:
        store.close()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
