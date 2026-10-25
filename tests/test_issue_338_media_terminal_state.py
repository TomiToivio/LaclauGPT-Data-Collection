"""A media object that cannot succeed must stop being retried (issue #338).

The media stage re-attempted the same two poison objects every hour forever: `failed` was not a
terminal status, so `enqueue_from_records` offered them again on the next cycle, and the only
record of the attempt was a count in a log line. These tests pin the bounded-attempt contract:
after `max_attempts` failures the object is dead-lettered with its sanitized reason, the queue no
longer offers it, and a cycle with nothing left reports nothing to attempt.

The database is a throwaway `CollectionStore`; nothing here touches the network or a live index.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from urllib.error import HTTPError

import pytest

from laclaugpt_data_collection.media import (
    DEFAULT_MAX_MEDIA_ATTEMPTS,
    TERMINAL_MEDIA_STATUSES,
    MediaDownloader,
)
from laclaugpt_data_collection.store import CollectionStore

SOURCE_URL = "https://example.invalid/item/1"
MEDIA_URL = "https://cdn.example.invalid/clip.mp4"


def _record() -> dict:
    return {
        "source_url": SOURCE_URL,
        "platform": "x",
        "collection_id": "ai26",
        "content": {
            "media_references": [{"url": MEDIA_URL, "kind": "video", "media_index": 0}]
        },
    }


def _http_error(code: int) -> HTTPError:
    return HTTPError(MEDIA_URL, code, "no", {}, None)  # type: ignore[arg-type]


def _downloader(tmp_path: Path, *, fetch, max_attempts: int | None = None) -> MediaDownloader:
    store = CollectionStore(tmp_path / "store")
    return MediaDownloader(store, fetcher=fetch, max_attempts=max_attempts)


def _cycle(downloader: MediaDownloader) -> list[dict]:
    jobs = downloader.enqueue_from_records([_record()])
    return downloader.run_queue(jobs) if jobs else []


def test_a_poison_object_is_dead_lettered_after_the_attempt_limit(tmp_path: Path) -> None:
    downloader = _downloader(tmp_path, fetch=lambda url: (_ for _ in ()).throw(_http_error(404)),
                             max_attempts=3)
    key = downloader.enqueue_from_records([_record()])[0].media_key

    first = _cycle(downloader)
    second = _cycle(downloader)
    third = _cycle(downloader)

    assert [item["status"] for item in first] == ["failed"]
    assert [item["status"] for item in second] == ["failed"]
    assert [item["status"] for item in third] == ["dead_letter"]
    state = downloader.store.media_known(key)
    assert state is not None
    assert state["terminal"] is True
    assert state["attempts"] == 3
    assert "HTTP 404" in (state["failure_reason"] or "")
    assert "attempt 3/3" in (state["failure_reason"] or "")


def test_a_dead_lettered_object_is_never_queued_again(tmp_path: Path) -> None:
    downloader = _downloader(tmp_path, fetch=lambda url: (_ for _ in ()).throw(_http_error(404)),
                             max_attempts=2)
    _cycle(downloader)
    _cycle(downloader)

    assert downloader.enqueue_from_records([_record()]) == []
    assert _cycle(downloader) == []


def test_an_attempt_limit_of_one_dead_letters_on_the_first_failure(tmp_path: Path) -> None:
    downloader = _downloader(tmp_path, fetch=lambda url: (_ for _ in ()).throw(_http_error(500)),
                             max_attempts=1)
    result = _cycle(downloader)
    assert [item["status"] for item in result] == ["dead_letter"]


def test_access_restricted_stays_terminal_and_is_not_retried(tmp_path: Path) -> None:
    """A session-bound TikTok object cannot be fetched again without the capturing browser."""
    record = _record()
    record["platform"] = "tiktok"
    record["content"]["media_references"][0]["url"] = "https://v16-webapp.tiktok.com/clip.mp4"
    store = CollectionStore(tmp_path / "store")
    downloader = MediaDownloader(
        store,
        fetcher=lambda url: (_ for _ in ()).throw(HTTPError(url, 403, "no", {}, None)),  # type: ignore[arg-type]
        max_attempts=3,
    )

    jobs = downloader.enqueue_from_records([record])
    assert [item["status"] for item in downloader.run_queue(jobs)] == ["access_restricted"]
    assert downloader.enqueue_from_records([record]) == []


def test_a_successful_retry_completes_and_is_not_terminal(tmp_path: Path) -> None:
    calls = {"n": 0}

    def fetch(url: str) -> tuple[bytes, str]:
        calls["n"] += 1
        if calls["n"] == 1:
            raise _http_error(503)
        return b"video-bytes", "video/mp4"

    downloader = _downloader(tmp_path, fetch=fetch, max_attempts=3)
    assert [item["status"] for item in _cycle(downloader)] == ["failed"]
    assert [item["status"] for item in _cycle(downloader)] == ["completed"]

    states = downloader.store.media_states(SOURCE_URL)
    assert len(states) == 1
    assert states[0]["status"] == "completed"
    assert states[0]["terminal"] is False
    assert states[0]["attempts"] == 2


def test_the_attempt_limit_defaults_and_honours_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    downloader = _downloader(tmp_path / "a", fetch=lambda url: (b"", ""))
    assert downloader.max_attempts == DEFAULT_MAX_MEDIA_ATTEMPTS

    monkeypatch.setenv("LACLAUGPT_MEDIA_MAX_ATTEMPTS", "5")
    configured = _downloader(tmp_path / "b", fetch=lambda url: (b"", ""))
    assert configured.max_attempts == 5

    monkeypatch.setenv("LACLAUGPT_MEDIA_MAX_ATTEMPTS", "not-a-number")
    ignored = _downloader(tmp_path / "c", fetch=lambda url: (b"", ""))
    assert ignored.max_attempts == DEFAULT_MAX_MEDIA_ATTEMPTS


def test_dead_letter_is_a_terminal_status(tmp_path: Path) -> None:
    assert "dead_letter" in TERMINAL_MEDIA_STATUSES


def test_an_old_media_index_gains_the_attempt_columns(tmp_path: Path) -> None:
    """A live index predates these columns; opening it must migrate, not fail."""
    root = tmp_path / "store"
    root.mkdir(parents=True)
    db = sqlite3.connect(root / "state.sqlite3")
    db.execute(
        """
        CREATE TABLE media_index (
            media_key TEXT PRIMARY KEY,
            platform TEXT, document_id TEXT, media_index INTEGER,
            url TEXT, local_path TEXT, sha256 TEXT,
            byte_size INTEGER, mime_type TEXT,
            status TEXT, failure_reason TEXT, http_status INTEGER,
            downloaded_at TEXT
        )
        """
    )
    db.execute(
        "INSERT INTO media_index (media_key, platform, document_id, media_index, url, status) "
        "VALUES ('ai26:x:abc:0', 'x', 'doc', 0, 'https://example.invalid/a.mp4', 'failed')"
    )
    db.commit()
    db.close()

    store = CollectionStore(root)
    known = store.media_known("ai26:x:abc:0")
    assert known is not None
    assert known["attempts"] == 0
    assert known["terminal"] is False
