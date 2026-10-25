"""A media object that cannot be downloaded must stop being retried (issue #338).

The stage had no dead-letter, backoff or poison-object quarantine. A permanently
broken object was re-enqueued on every cycle, so `attempted=2, completed=0, failed=2`
repeated hourly, the stage made no progress, and `runner_status=1` every hour. Cycles
that also did useful work hid it: `attempted=147, failed=2` reads like a 98.6%
success rate.

These tests pin the three facts that make the loop end:

* a failure is counted on the object and survives the pre-fetch ``running`` write;
* the object is retired as a terminal ``dead_letter`` after a bounded number of
  attempts, keeping its last reason;
* a retired object is never enqueued again, and is not counted as a live failure,
  so the cycle can exit 0.
"""
from __future__ import annotations

import pytest

from laclaugpt_data_collection.media import (
    DEFAULT_MAX_MEDIA_ATTEMPTS,
    TERMINAL_MEDIA_STATUSES,
    MediaDownloader,
)
from laclaugpt_data_collection.store import CollectionStore


class _FailingFetcher:
    def __init__(self, exc: Exception | None = None) -> None:
        self.calls = 0
        self.exc = exc or OSError("host unreachable")

    def __call__(self, url: str) -> tuple[bytes, str]:
        self.calls += 1
        raise self.exc


def _record(url: str = "https://cdn.example.invalid/a.jpg") -> dict:
    return {
        "source_url": "https://example.invalid/post/1",
        "collection_id": "ai26",
        "platform": "x",
        "content": {
            "media_references": [{"url": url, "kind": "image", "media_index": 0}]
        },
    }


@pytest.fixture()
def store(tmp_path):
    return CollectionStore(tmp_path)


def test_a_failure_is_counted_and_survives_the_running_write(store):
    """``running`` is written before the fetch; it must not reset the counter."""
    fetcher = _FailingFetcher()
    downloader = MediaDownloader(store, workers=1, fetcher=fetcher, max_attempts=3)

    jobs = downloader.enqueue_from_records([_record()])
    assert len(jobs) == 1

    for expected in (1, 2):
        results = downloader.run_queue(jobs)
        assert results[0]["status"] == "failed"
        assert results[0]["attempts"] == expected
        state = store.media_known(jobs[0].media_key)
        assert state["attempts"] == expected
        assert state["status"] == "failed"
        jobs = downloader.enqueue_from_records([_record()])


def test_the_bounded_attempt_is_retired_as_a_dead_letter(store):
    fetcher = _FailingFetcher()
    downloader = MediaDownloader(store, workers=1, fetcher=fetcher, max_attempts=3)

    for _ in range(2):
        downloader.run_queue(downloader.enqueue_from_records([_record()]))

    jobs = downloader.enqueue_from_records([_record()])
    results = downloader.run_queue(jobs)

    assert results[0]["status"] == "dead_letter"
    assert "gave up after 3 attempts" in results[0]["error"]
    state = store.media_known(jobs[0].media_key)
    assert state["status"] == "dead_letter"
    assert state["attempts"] == 3
    # The reason is kept on the object, not only in the cycle summary.
    assert "gave up after 3 attempts" in store.media_states(
        "https://example.invalid/post/1", collection_id="ai26"
    )[0]["failure_reason"]


def test_a_retired_object_is_never_enqueued_again(store):
    """The whole point: a drained stage stops attempting the same object."""
    downloader = MediaDownloader(
        store, workers=1, fetcher=_FailingFetcher(), max_attempts=2
    )
    downloader.run_queue(downloader.enqueue_from_records([_record()]))
    downloader.run_queue(downloader.enqueue_from_records([_record()]))

    assert downloader.enqueue_from_records([_record()]) == []
    assert "dead_letter" in TERMINAL_MEDIA_STATUSES


def test_a_success_clears_the_failure_history(store):
    downloader = MediaDownloader(
        store, workers=1, fetcher=_FailingFetcher(), max_attempts=5
    )
    downloader.run_queue(downloader.enqueue_from_records([_record()]))
    key = downloader.enqueue_from_records([_record()])[0].media_key
    assert store.media_known(key)["attempts"] == 1

    ok = MediaDownloader(store, workers=1, fetcher=lambda url: (b"bytes", "image/jpeg"))
    results = ok.run_queue(ok.enqueue_from_records([_record()]))

    assert results[0]["status"] == "completed"
    assert store.media_known(key)["attempts"] == 0


def test_the_default_bound_is_finite_and_configurable(store, monkeypatch):
    assert DEFAULT_MAX_MEDIA_ATTEMPTS >= 1
    assert MediaDownloader(store, fetcher=lambda u: (b"", "")).max_attempts == (
        DEFAULT_MAX_MEDIA_ATTEMPTS
    )

    monkeypatch.setenv("LACLAUGPT_MEDIA_MAX_ATTEMPTS", "2")
    assert MediaDownloader(store, fetcher=lambda u: (b"", "")).max_attempts == 2

    monkeypatch.setenv("LACLAUGPT_MEDIA_MAX_ATTEMPTS", "not-a-number")
    assert MediaDownloader(store, fetcher=lambda u: (b"", "")).max_attempts == (
        DEFAULT_MAX_MEDIA_ATTEMPTS
    )

    # A zero or negative bound would retire everything on first failure; floor it.
    assert MediaDownloader(store, fetcher=lambda u: (b"", ""), max_attempts=0).max_attempts == 1


def test_an_existing_media_index_gains_the_attempt_column(tmp_path):
    """The live store predates the counter; opening it must migrate in place."""
    import sqlite3

    db = tmp_path / "state.sqlite3"
    db.parent.mkdir(parents=True, exist_ok=True)
    legacy = sqlite3.connect(db)
    legacy.execute(
        """
        CREATE TABLE media_index (
            media_key TEXT PRIMARY KEY, platform TEXT, document_id TEXT,
            media_index INTEGER, url TEXT, local_path TEXT, sha256 TEXT,
            byte_size INTEGER, mime_type TEXT, status TEXT, failure_reason TEXT,
            http_status INTEGER, downloaded_at TEXT
        )
        """
    )
    legacy.execute(
        "INSERT INTO media_index (media_key, status) VALUES ('k', 'failed')"
    )
    legacy.commit()
    legacy.close()

    store = CollectionStore(tmp_path)
    state = store.media_known("k")

    assert state["attempts"] == 0
    assert state["status"] == "failed"
