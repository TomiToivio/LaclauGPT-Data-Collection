"""Local-first storage backends for canonical Collection records."""
from __future__ import annotations

import csv
import json
import sqlite3
from collections.abc import Iterable
from pathlib import Path

from ..models import CanonicalRecord


class SQLiteRecordStore:
    """Persist canonical records using source_url as semantic identity."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def _ensure_schema(self) -> None:
        with self._connect() as con:
            columns = {
                row[1]
                for row in con.execute("PRAGMA table_info(records)").fetchall()
            }
            if columns and "source_url" not in columns:
                self._migrate_legacy_schema(con)
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS records (
                    source_url TEXT PRIMARY KEY,
                    schema_version TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )

    def _migrate_legacy_schema(self, con: sqlite3.Connection) -> None:
        """Bounded migration from the former platform/document_id table."""
        rows = con.execute("SELECT payload_json FROM records").fetchall()
        con.execute("ALTER TABLE records RENAME TO records_legacy")
        con.execute(
            """
            CREATE TABLE records (
                source_url TEXT PRIMARY KEY,
                schema_version TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )
            """
        )
        for (payload_json,) in rows:
            payload = json.loads(payload_json)
            try:
                record = CanonicalRecord.model_validate(payload)
            except Exception:
                from ..models import NormalizedRecord

                record = NormalizedRecord(**payload)
            con.execute(
                "INSERT OR REPLACE INTO records(source_url, schema_version, payload_json) VALUES (?, ?, ?)",
                (record.source_url, record.schema_version, record.model_dump_json()),
            )
        con.execute("DROP TABLE records_legacy")

    def upsert(self, record: CanonicalRecord) -> None:
        payload = record.model_dump_json()
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO records(source_url, schema_version, payload_json)
                VALUES (?, ?, ?)
                ON CONFLICT(source_url)
                DO UPDATE SET schema_version = excluded.schema_version,
                              payload_json = excluded.payload_json
                """,
                (record.source_url, record.schema_version, payload),
            )

    def upsert_many(self, records: Iterable[CanonicalRecord]) -> None:
        rows = [
            (record.source_url, record.schema_version, record.model_dump_json())
            for record in records
        ]
        if not rows:
            return
        with self._connect() as con:
            con.executemany(
                """
                INSERT INTO records(source_url, schema_version, payload_json)
                VALUES (?, ?, ?)
                ON CONFLICT(source_url)
                DO UPDATE SET schema_version = excluded.schema_version,
                              payload_json = excluded.payload_json
                """,
                rows,
            )

    def contains(self, source_url: str) -> bool:
        from ..models import canonicalize_source_url

        identity = canonicalize_source_url(source_url)
        with self._connect() as con:
            row = con.execute(
                "SELECT 1 FROM records WHERE source_url = ? LIMIT 1", (identity,)
            ).fetchone()
        return row is not None

    def get(self, source_url: str) -> CanonicalRecord | None:
        from ..models import canonicalize_source_url

        identity = canonicalize_source_url(source_url)
        with self._connect() as con:
            row = con.execute(
                "SELECT payload_json FROM records WHERE source_url = ?", (identity,)
            ).fetchone()
        return CanonicalRecord.model_validate_json(row[0]) if row else None

    def all(self) -> list[CanonicalRecord]:
        with self._connect() as con:
            rows = con.execute("SELECT payload_json FROM records ORDER BY source_url").fetchall()
        return [CanonicalRecord.model_validate_json(payload) for (payload,) in rows]

    def export_jsonl(self, path: str | Path) -> None:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("w", encoding="utf-8") as fh:
            for record in self.all():
                fh.write(record.model_dump_json())
                fh.write("\n")

    def export_csv(self, path: str | Path) -> None:
        """Flat canonical CSV with deterministic JSON for nested sections."""
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        fields = [
            "schema_version",
            "source_url",
            "source_native_ids",
            "source",
            "content",
            "evidence",
            "analysis",
            "provenance",
            "review",
            "legacy",
        ]
        with destination.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            for record in self.all():
                payload = record.model_dump(mode="json")
                writer.writerow(
                    {
                        "schema_version": record.schema_version,
                        "source_url": record.source_url,
                        **{
                            field: json.dumps(payload[field], ensure_ascii=False, sort_keys=True)
                            for field in fields[2:]
                        },
                    }
                )


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
