"""Durable collection storage for raw captures, canonical JSONL, manifests and state."""
from __future__ import annotations

import itertools
import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path


def utc_stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


class CollectionStore:
    """Filesystem-backed capture/state store used by the Firefox backend.

    This legacy-compatible facade accepts both historical flat records and the
    current canonical nested record. Deduplication is anchored to canonical
    ``source_url`` whenever available.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.raw_dir = self.root / "raw"
        self.normalized_dir = self.root / "normalized"
        self.manifests_dir = self.root / "manifests"
        self.media_dir = self.root / "media"
        for directory in (self.raw_dir, self.normalized_dir, self.manifests_dir, self.media_dir):
            directory.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.root / "state.sqlite3", check_same_thread=False)
        self._db_lock = threading.Lock()
        self._counter = itertools.count()
        self._closed = False
        self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS seen_posts (
                platform TEXT NOT NULL,
                document_id TEXT NOT NULL,
                first_seen TEXT NOT NULL,
                normalized_ref TEXT,
                PRIMARY KEY (platform, document_id)
            )
            """
        )
        self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS checkpoints (
                account TEXT NOT NULL,
                platform TEXT NOT NULL,
                cursor TEXT,
                last_run TEXT,
                last_status TEXT,
                PRIMARY KEY (account, platform)
            )
            """
        )
        self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS media_index (
                media_key TEXT PRIMARY KEY,
                platform TEXT, document_id TEXT, media_index INTEGER,
                url TEXT, local_path TEXT, sha256 TEXT,
                byte_size INTEGER, mime_type TEXT,
                status TEXT, failure_reason TEXT, http_status INTEGER,
                downloaded_at TEXT
            )
            """
        )
        self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS media_references (
                url TEXT NOT NULL,
                media_key TEXT NOT NULL,
                platform TEXT NOT NULL,
                document_id TEXT NOT NULL,
                media_index INTEGER NOT NULL,
                PRIMARY KEY (url, media_key)
            )
            """
        )
        self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS captured_media (
                url TEXT PRIMARY KEY,
                local_path TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                byte_size INTEGER NOT NULL,
                mime_type TEXT NOT NULL,
                captured_at TEXT NOT NULL
            )
            """
        )
        self._migrate_media_index()
        self._db.commit()

    def _migrate_media_index(self) -> None:
        """Add the attempt-tracking columns an older database does not have (issue #338).

        Additive and idempotent by design: ``CREATE TABLE IF NOT EXISTS`` above does nothing to a
        table that already exists, so a database written by an earlier version would otherwise
        never gain the columns the retry policy reads. ``ALTER TABLE ... ADD COLUMN`` never
        rewrites a row and never drops one, so this is safe to run on the live index.
        """
        existing = {row[1] for row in self._db.execute("PRAGMA table_info(media_index)")}
        if "attempts" not in existing:
            self._db.execute(
                "ALTER TABLE media_index ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0"
            )
        if "last_attempt_at" not in existing:
            self._db.execute("ALTER TABLE media_index ADD COLUMN last_attempt_at TEXT")

    def append_raw(self, platform: str, payload: dict) -> str:
        day = datetime.now(UTC).strftime("%Y%m%d")
        directory = self.raw_dir / platform / day
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"capture-{utc_stamp()}-{next(self._counter):08x}.ndjson"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
        return path.relative_to(self.root).as_posix()

    @staticmethod
    def _record_identity(record: dict) -> tuple[str, str]:
        source = record.get("source") or {}
        native_ids = record.get("source_native_ids") or {}
        platform = str(record.get("platform") or source.get("platform") or "source")
        source_url = str(record.get("source_url") or "")
        native_id = str(record.get("document_id") or native_ids.get("document_id") or "")
        identity = source_url or native_id
        if not identity:
            raise ValueError("record requires canonical source_url or source-native identifier")
        return platform, identity

    def upsert_post(self, record: dict, raw_ref: str) -> bool:
        """Insert a normalized/canonical record if new; returns True when inserted."""
        platform, identity = self._record_identity(record)
        with self._db_lock:
            cur = self._db.execute(
                "SELECT 1 FROM seen_posts WHERE platform=? AND document_id=?",
                (platform, identity),
            )
            if cur.fetchone():
                return False
            path = self.normalized_dir / f"{platform}.jsonl"
            payload = dict(record)
            if "source" in payload:
                source = dict(payload.get("source") or {})
                source.setdefault("raw_ref", raw_ref)
                payload["source"] = source
            else:
                payload["raw_ref"] = raw_ref
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
            self._db.execute(
                "INSERT INTO seen_posts (platform, document_id, first_seen, normalized_ref) VALUES (?, ?, ?, ?)",
                (
                    platform,
                    identity,
                    datetime.now(UTC).isoformat(timespec="seconds"),
                    path.relative_to(self.root).as_posix(),
                ),
            )
            self._db.commit()
        return True

    def seen_count(self, platform: str | None = None) -> int:
        with self._db_lock:
            if platform:
                cur = self._db.execute(
                    "SELECT COUNT(*) FROM seen_posts WHERE platform=?", (platform,)
                )
            else:
                cur = self._db.execute("SELECT COUNT(*) FROM seen_posts")
            return int(cur.fetchone()[0])

    def checkpoint(
        self,
        account: str,
        platform: str,
        cursor: str | None = None,
        status: str = "ok",
    ) -> None:
        with self._db_lock:
            self._db.execute(
                """
                INSERT INTO checkpoints (account, platform, cursor, last_run, last_status)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(account, platform) DO UPDATE SET
                    cursor=excluded.cursor, last_run=excluded.last_run,
                    last_status=excluded.last_status
                """,
                (account, platform, cursor, datetime.now(UTC).isoformat(timespec="seconds"), status),
            )
            self._db.commit()

    def get_cursor(self, account: str, platform: str) -> str | None:
        with self._db_lock:
            cur = self._db.execute(
                "SELECT cursor FROM checkpoints WHERE account=? AND platform=?",
                (account, platform),
            )
            row = cur.fetchone()
            return row[0] if row else None

    def failing_accounts(self) -> list[tuple]:
        with self._db_lock:
            return self._db.execute(
                "SELECT account, platform, last_status FROM checkpoints WHERE last_status != 'ok'"
            ).fetchall()

    def media_known(self, media_key: str) -> dict | None:
        with self._db_lock:
            row = self._db.execute(
                "SELECT local_path, sha256, status, attempts, last_attempt_at "
                "FROM media_index WHERE media_key=?",
                (media_key,),
            ).fetchone()
            if not row:
                return None
            return {
                "local_path": row[0],
                "sha256": row[1],
                "status": row[2],
                "attempts": int(row[3] or 0),
                "last_attempt_at": row[4],
            }

    def record_media_failure(
        self,
        media_key: str,
        platform: str,
        document_id: str,
        media_index: int,
        url: str,
        status: str,
        failure_reason: str | None,
        http_status: int | None,
    ) -> int:
        """Persist one failed attempt and return the object's consecutive attempt count.

        Issue #338: the media index used to be written with ``INSERT OR REPLACE``, which threw
        away the previous row — including any notion of how often this object had already failed.
        Without that number there is no bounded policy: an object that fails permanently is
        re-enqueued every cycle forever, and a cycle whose whole backlog is poison reports
        ``attempted=2 completed=0 failed=2`` indefinitely.

        The count is incremented in the database rather than read-then-written in Python, so two
        workers racing on the same key still produce a monotonic count.
        """
        now = datetime.now(UTC).isoformat(timespec="seconds")
        with self._db_lock:
            self._db.execute(
                """
                INSERT INTO media_index
                    (media_key, platform, document_id, media_index, url, local_path, sha256,
                     byte_size, mime_type, status, failure_reason, http_status, downloaded_at,
                     attempts, last_attempt_at)
                VALUES (?, ?, ?, ?, ?, NULL, NULL, NULL, '', ?, ?, ?, ?, 1, ?)
                ON CONFLICT(media_key) DO UPDATE SET
                    status = excluded.status,
                    failure_reason = excluded.failure_reason,
                    http_status = excluded.http_status,
                    downloaded_at = excluded.downloaded_at,
                    attempts = COALESCE(media_index.attempts, 0) + 1,
                    last_attempt_at = excluded.last_attempt_at
                """,
                (media_key, platform, document_id, media_index, url, status,
                 failure_reason, http_status, now, now),
            )
            row = self._db.execute(
                "SELECT attempts FROM media_index WHERE media_key=?", (media_key,)
            ).fetchone()
            self._db.commit()
        return int(row[0]) if row and row[0] is not None else 1

    def media_states(self, source_id: str, *, collection_id: str | None = None) -> list[dict]:
        """Return durable downloader state for one canonical source.

        The current media table predates an explicit ``collection_id`` column,
        so campaign isolation is recovered from the collection-prefixed
        ``media_key`` written by :class:`MediaDownloader`.
        """
        with self._db_lock:
            rows = self._db.execute(
                """
                SELECT media_key, media_index, url, local_path, sha256, byte_size,
                       mime_type, status, failure_reason, http_status, downloaded_at
                FROM media_index WHERE document_id=? ORDER BY media_index, media_key
                """,
                (source_id,),
            ).fetchall()
        states = [
            {
                "media_key": row[0],
                "media_index": row[1],
                "url": row[2],
                "local_path": row[3],
                "sha256": row[4],
                "byte_size": row[5],
                "mime_type": row[6],
                "status": row[7],
                "failure_reason": row[8],
                "http_status": row[9],
                "downloaded_at": row[10],
            }
            for row in rows
        ]
        if collection_id:
            prefix = f"{collection_id}:"
            states = [state for state in states if str(state["media_key"]).startswith(prefix)]
        return states

    def record_media(
        self,
        media_key: str,
        platform: str,
        document_id: str,
        media_index: int,
        url: str,
        local_path: str | None,
        sha256: str | None,
        byte_size: int | None,
        mime_type: str,
        status: str,
        failure_reason: str | None = None,
        http_status: int | None = None,
    ) -> None:
        with self._db_lock:
            # An upsert rather than INSERT OR REPLACE: REPLACE deletes the row and inserts a new
            # one, so every column it does not name — including the attempt count added for
            # issue #338 — silently reverts to its default. The downloader writes "running" at the
            # start of every attempt, which would have reset the budget on each try and made the
            # limit unreachable. Naming the columns keeps that state intact.
            self._db.execute(
                """
                INSERT INTO media_index
                (media_key, platform, document_id, media_index, url, local_path,
                 sha256, byte_size, mime_type, status, failure_reason, http_status,
                 downloaded_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(media_key) DO UPDATE SET
                    platform = excluded.platform,
                    document_id = excluded.document_id,
                    media_index = excluded.media_index,
                    url = excluded.url,
                    local_path = excluded.local_path,
                    sha256 = excluded.sha256,
                    byte_size = excluded.byte_size,
                    mime_type = excluded.mime_type,
                    status = excluded.status,
                    failure_reason = excluded.failure_reason,
                    http_status = excluded.http_status,
                    downloaded_at = excluded.downloaded_at
                """,
                (
                    media_key,
                    platform,
                    document_id,
                    media_index,
                    url,
                    local_path,
                    sha256,
                    byte_size,
                    mime_type,
                    status,
                    failure_reason,
                    http_status,
                    datetime.now(UTC).isoformat(timespec="seconds"),
                ),
            )
            self._db.commit()

    def register_media_reference(
        self,
        url: str,
        media_key: str,
        platform: str,
        document_id: str,
        media_index: int,
    ) -> None:
        """Persist canonical linkage before or after capture bytes arrive."""
        with self._db_lock:
            self._db.execute(
                """
                INSERT OR IGNORE INTO media_references
                (url, media_key, platform, document_id, media_index)
                VALUES (?, ?, ?, ?, ?)
                """,
                (url, media_key, platform, document_id, media_index),
            )
            self._db.commit()

    def media_references_for_url(self, url: str) -> list[dict]:
        with self._db_lock:
            rows = self._db.execute(
                """
                SELECT media_key, platform, document_id, media_index
                FROM media_references WHERE url=? ORDER BY media_key
                """,
                (url,),
            ).fetchall()
        return [
            {
                "media_key": row[0],
                "platform": row[1],
                "document_id": row[2],
                "media_index": row[3],
            }
            for row in rows
        ]

    def record_captured_media(
        self,
        url: str,
        local_path: str,
        sha256: str,
        byte_size: int,
        mime_type: str,
    ) -> None:
        with self._db_lock:
            self._db.execute(
                """
                INSERT OR REPLACE INTO captured_media
                (url, local_path, sha256, byte_size, mime_type, captured_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    url,
                    local_path,
                    sha256,
                    byte_size,
                    mime_type,
                    datetime.now(UTC).isoformat(timespec="seconds"),
                ),
            )
            self._db.commit()

    def captured_media(self, url: str) -> dict | None:
        with self._db_lock:
            row = self._db.execute(
                """
                SELECT local_path, sha256, byte_size, mime_type, captured_at
                FROM captured_media WHERE url=?
                """,
                (url,),
            ).fetchone()
        if not row:
            return None
        return {
            "local_path": row[0],
            "sha256": row[1],
            "byte_size": row[2],
            "mime_type": row[3],
            "captured_at": row[4],
        }

    def write_manifest(self, manifest: dict) -> Path:
        path = self.manifests_dir / f"run-{utc_stamp()}.json"
        if path.exists():
            index = 1
            while True:
                candidate = path.with_name(f"{path.stem}-{index}{path.suffix}")
                if not candidate.exists():
                    path = candidate
                    break
                index += 1
        path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=1, default=str),
            encoding="utf-8",
        )
        return path

    def close(self) -> None:
        if self._closed:
            return
        with self._db_lock:
            self._db.close()
            self._closed = True
