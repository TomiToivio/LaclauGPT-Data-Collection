"""Durable collection storage for raw captures, canonical JSONL, manifests and state."""
from __future__ import annotations

import itertools
import json
import re
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def utc_stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


#: Payload keys whose values are credentials, not research data. The browser extension
#: posts every X GraphQL response, and some of them (notably ``grok_account_jwt``) carry
#: live bearer tokens; storing them verbatim puts a working credential on disk.
_SECRET_KEY = re.compile(
    r"(?i)(?:^|[_-])(jwt|token|secret|password|passwd|authorization|cookie|session|api_?key|bearer)(?:$|[_-])"
)
#: A bare JWT anywhere in a string value, regardless of the key it sits under.
_JWT_VALUE = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")
REDACTED = "[REDACTED]"


def redact_secrets(value: Any) -> Any:
    """Return ``value`` with credential-bearing entries replaced by ``[REDACTED]``.

    Structural information is preserved (keys and list lengths stay), so a raw capture
    remains useful for diagnosing a parser failure without keeping a token that could be
    replayed. Applied in :meth:`CollectionStore.append_raw`, i.e. on every platform, so no
    caller can forget it.
    """
    if isinstance(value, dict):
        cleaned: dict[Any, Any] = {}
        for key, item in value.items():
            if isinstance(key, str) and _SECRET_KEY.search(key) and not isinstance(item, (dict, list)):
                cleaned[key] = REDACTED
            else:
                cleaned[key] = redact_secrets(item)
        return cleaned
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    if isinstance(value, str) and _JWT_VALUE.search(value):
        return _JWT_VALUE.sub(REDACTED, value)
    return value


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
                downloaded_at TEXT,
                attempts INTEGER NOT NULL DEFAULT 0,
                terminal INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        # Issue #338: a media object that will never succeed must stop being retried. An
        # existing database predates the two columns, so they are added in place rather than
        # requiring a rebuild of state that records live downloads.
        columns = {row[1] for row in self._db.execute("PRAGMA table_info(media_index)")}
        for name, ddl in (("attempts", "INTEGER NOT NULL DEFAULT 0"),
                          ("terminal", "INTEGER NOT NULL DEFAULT 0")):
            if name not in columns:
                self._db.execute(f"ALTER TABLE media_index ADD COLUMN {name} {ddl}")
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
        self._db.commit()

    def append_raw(self, platform: str, payload: dict) -> str:
        day = datetime.now(UTC).strftime("%Y%m%d")
        directory = self.raw_dir / platform / day
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"capture-{utc_stamp()}-{next(self._counter):08x}.ndjson"
        # Write-then-rename: a crash mid-write must not leave a half-line that later
        # breaks every reader of raw/ (two such truncated lines were observed on the
        # AI26 capture host, #392). The temp name is unique per file, so concurrent
        # writers cannot clobber each other's staging file.
        line = json.dumps(redact_secrets(payload), ensure_ascii=False, default=str) + "\n"
        staging = path.with_name(path.name + ".tmp")
        staging.write_text(line, encoding="utf-8")
        staging.replace(path)
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
                handle.write(json.dumps(redact_secrets(payload), ensure_ascii=False, default=str) + "\n")
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
                "SELECT local_path, sha256, status, attempts, terminal, failure_reason "
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
                "terminal": bool(row[4]),
                "failure_reason": row[5],
            }

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
                       mime_type, status, failure_reason, http_status, downloaded_at,
                       attempts, terminal
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
                "attempts": int(row[11] or 0),
                "terminal": bool(row[12]),
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
        attempts: int = 0,
        terminal: bool = False,
    ) -> None:
        with self._db_lock:
            self._db.execute(
                """
                INSERT OR REPLACE INTO media_index
                (media_key, platform, document_id, media_index, url, local_path,
                 sha256, byte_size, mime_type, status, failure_reason, http_status,
                 downloaded_at, attempts, terminal)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    int(attempts),
                    1 if terminal else 0,
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
