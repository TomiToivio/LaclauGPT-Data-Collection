"""Local-first storage backends: SQLite records and filesystem objects."""
from __future__ import annotations

import csv
import json
import sqlite3
from collections.abc import Iterable
from pathlib import Path

from ..models import NormalizedRecord


class SQLiteRecordStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def _ensure_schema(self) -> None:
        with self._connect() as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS records (
                    platform TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    PRIMARY KEY (platform, document_id)
                )
                """
            )

    def upsert(self, record: NormalizedRecord) -> None:
        payload = record.model_dump_json()
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO records(platform, document_id, payload_json)
                VALUES (?, ?, ?)
                ON CONFLICT(platform, document_id)
                DO UPDATE SET payload_json = excluded.payload_json
                """,
                (record.platform, record.document_id, payload),
            )

    def upsert_many(self, records: Iterable[NormalizedRecord]) -> None:
        rows = [
            (record.platform, record.document_id, record.model_dump_json())
            for record in records
        ]
        if not rows:
            return
        with self._connect() as con:
            con.executemany(
                """
                INSERT INTO records(platform, document_id, payload_json)
                VALUES (?, ?, ?)
                ON CONFLICT(platform, document_id)
                DO UPDATE SET payload_json = excluded.payload_json
                """,
                rows,
            )

    def contains(self, platform: str, document_id: str) -> bool:
        with self._connect() as con:
            row = con.execute(
                "SELECT 1 FROM records WHERE platform = ? AND document_id = ? LIMIT 1",
                (platform, document_id),
            ).fetchone()
        return row is not None

    def export_jsonl(self, path: str | Path) -> None:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as con, destination.open("w", encoding="utf-8") as fh:
            for (payload,) in con.execute(
                "SELECT payload_json FROM records ORDER BY platform, document_id"
            ):
                fh.write(payload)
                fh.write("\n")

    def export_csv(self, path: str | Path) -> None:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        fields = [
            "schema_version",
            "document_id",
            "platform",
            "author",
            "timestamp",
            "source_url",
            "text",
            "raw_ref",
        ]
        with self._connect() as con, destination.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            for (payload,) in con.execute(
                "SELECT payload_json FROM records ORDER BY platform, document_id"
            ):
                record = json.loads(payload)
                writer.writerow({field: record.get(field, "") for field in fields})


class FilesystemObjectStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        clean_key = key.lstrip("/")
        path = (self.root / clean_key).resolve()
        root = self.root.resolve()
        if root != path and root not in path.parents:
            raise ValueError("object key escapes configured root")
        return path

    def put_bytes(self, key: str, payload: bytes, *, content_type: str = "application/octet-stream") -> str:
        del content_type
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return path.relative_to(self.root.resolve()).as_posix()

    def put_text(self, key: str, payload: str, *, content_type: str = "text/plain; charset=utf-8") -> str:
        del content_type
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload, encoding="utf-8")
        return path.relative_to(self.root.resolve()).as_posix()
