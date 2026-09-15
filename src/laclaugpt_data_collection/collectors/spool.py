"""Privacy-safe offline directory spool for laptop/HPC collection workflows."""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from ..models import NormalizedRecord


@dataclass(slots=True)
class SpoolResult:
    processed: int = 0
    succeeded: int = 0
    failed: int = 0


class DirectorySpool:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.incoming = self.root / "incoming"
        self.processed = self.root / "processed"
        self.errors = self.root / "error"
        for path in (self.incoming, self.processed, self.errors):
            path.mkdir(parents=True, exist_ok=True)

    def enqueue(self, record: NormalizedRecord) -> Path:
        safe_name = record.source_native_ids.get("document_id") or record.source_url.replace("/", "_").replace(":", "_")
        path = self.incoming / f"{safe_name[:120]}.json"
        path.write_text(record.model_dump_json(indent=2), encoding="utf-8")
        return path

    def process_file(self, path: str | Path) -> NormalizedRecord:
        source = Path(path)
        try:
            record = NormalizedRecord.model_validate(json.loads(source.read_text(encoding="utf-8")))
        except Exception:
            shutil.move(str(source), self.errors / source.name)
            raise
        shutil.move(str(source), self.processed / source.name)
        return record

    def process_all(self) -> tuple[SpoolResult, list[NormalizedRecord]]:
        summary = SpoolResult()
        records: list[NormalizedRecord] = []
        for path in sorted(self.incoming.glob("*.json")):
            summary.processed += 1
            try:
                records.append(self.process_file(path))
                summary.succeeded += 1
            except Exception:
                summary.failed += 1
        return summary, records
