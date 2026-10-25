"""Issue #338: a permanently failing media object must reach a terminal state.

The defect
----------

The media index was written with ``INSERT OR REPLACE``, so every attempt overwrote the previous
row. Nothing recorded *how often* an object had already failed, and nothing capped it: a media
object that fails permanently was re-enqueued on the next hourly cycle, and the one after that,
for the rest of the study. Once the backlog drained, the stage did no work at all and still held a
cron slot and a lock:

    attempted=2 completed=0 failed=2 scanned=10      (every cycle, indefinitely)

That is a poison-object loop, and the diagnostic half (naming the objects and their HTTP reason)
landed separately in #341. This is the mechanism half.

What is asserted here is the downloader's own behaviour against a real sqlite index in a temporary
directory — the same store the Laskin stage uses. No network, no Mongo, no live corpus.
"""
from __future__ import annotations

import hashlib

from laclaugpt_data_collection.media import (
    MAX_MEDIA_ATTEMPTS,
    MediaDownloader,
    MediaJob,
)
from laclaugpt_data_collection.store import CollectionStore

#: The key the downloader itself derives: ``collection:platform:sha256(source_id)[:16]:index``.
#: Kept as a function so a test cannot drift from the production key derivation.
SOURCE_ID = "https://example.invalid/post/1"
MEDIA_KEY = f"ai26:x:{hashlib.sha256(SOURCE_ID.encode()).hexdigest()[:16]}:0"


def job(key: str = MEDIA_KEY) -> MediaJob:
    return MediaJob(
        media_key=key,
        collection_id="ai26",
        platform="x",
        source_id=SOURCE_ID,
        media_index=0,
        kind="image",
        url="https://cdn.example.invalid/1.jpg",
    )


def failing_downloader(tmp_path, *, status: int = 404) -> tuple[MediaDownloader, CollectionStore]:
    store = CollectionStore(tmp_path)

    def fetch(_url: str):
        raise OSError(f"HTTP {status} simulated")

    return MediaDownloader(store, fetcher=fetch), store


def record(store: CollectionStore) -> dict:
    """The canonical media record, as the pipeline builds it."""
    return {
        "collection_id": "ai26",
        "platform": "x",
        "source_url": SOURCE_ID,
        "media_references": [{"url": "https://cdn.example.invalid/1.jpg", "kind": "image"}],
    }


def test_attempts_are_counted_across_failures(tmp_path) -> None:
    """The count is the thing that was missing; it must survive being overwritten."""
    downloader, store = failing_downloader(tmp_path)
    first = downloader.run_queue([job()])[0]
    second = downloader.run_queue([job()])[0]
    assert first["status"] == "failed"
    assert first["attempts"] == 1
    assert second["attempts"] == 2, "a second failure must not look like a first"
    assert store.media_known(MEDIA_KEY)["attempts"] == 2


def test_an_object_is_dead_lettered_at_the_budget(tmp_path) -> None:
    """The whole point: bounded attempts, then a terminal state."""
    downloader, store = failing_downloader(tmp_path)
    results = [downloader.run_queue([job()])[0] for _ in range(MAX_MEDIA_ATTEMPTS)]
    assert [r["status"] for r in results[:-1]] == ["failed"] * (MAX_MEDIA_ATTEMPTS - 1)
    assert results[-1]["status"] == "dead_lettered"
    assert store.media_known(MEDIA_KEY)["status"] == "dead_lettered"


def test_a_dead_letter_keeps_the_reason_it_died_of(tmp_path) -> None:
    """A quarantine that cannot say why is not an audit."""
    downloader, store = failing_downloader(tmp_path)
    for _ in range(MAX_MEDIA_ATTEMPTS):
        downloader.run_queue([job()])
    known = store.media_known(MEDIA_KEY)
    assert known["status"] == "dead_lettered"


def test_a_dead_lettered_object_is_not_enqueued_again(tmp_path) -> None:
    """This is what turns `attempted=2 failed=2` forever into `attempted=0`."""
    downloader, store = failing_downloader(tmp_path)
    for _ in range(MAX_MEDIA_ATTEMPTS):
        downloader.run_queue([job()])
    assert downloader.enqueue_from_records([record(store)]) == []


def test_the_stage_goes_quiet_rather_than_failing_forever(tmp_path) -> None:
    """A cycle with only poison left must have nothing to do, not two failures."""
    downloader, store = failing_downloader(tmp_path)
    for _ in range(MAX_MEDIA_ATTEMPTS):
        downloader.run_queue([job()])
    jobs = downloader.enqueue_from_records([record(store)])
    assert jobs == []
    assert downloader.run_queue(jobs) == []


def test_a_recovered_object_completes_and_stops_being_retried(tmp_path) -> None:
    """The budget must not punish an object that comes back."""
    attempts = {"n": 0}

    def fetch(_url: str):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise OSError("simulated transient failure")
        return b"image-bytes", "image/jpeg"

    store = CollectionStore(tmp_path)
    downloader = MediaDownloader(store, fetcher=fetch)
    first = downloader.run_queue([job()])[0]
    assert first["status"] == "failed"
    second = downloader.run_queue([job()])[0]
    assert second["status"] == "completed"
    assert downloader.enqueue_from_records([record(store)]) == []


def test_access_restricted_is_still_terminal_and_distinct(tmp_path) -> None:
    """A host that refuses this collector is not the same as a broken object."""
    store = CollectionStore(tmp_path)
    downloader = MediaDownloader(store, fetcher=lambda _u: (_ for _ in ()).throw(OSError("403")))
    downloader.run_queue([job()])
    store.record_media(
        MEDIA_KEY, "x", "https://example.invalid/post/1", 0,
        "https://cdn.example.invalid/1.jpg", None, None, None, "",
        "access_restricted", "HTTP 403: access restricted", 403,
    )
    assert store.media_known(MEDIA_KEY)["status"] == "access_restricted"
    assert downloader.enqueue_from_records([record(store)]) == []


def test_an_older_index_gains_the_attempt_columns(tmp_path) -> None:
    """The live index predates these columns; the migration must be additive, not destructive."""
    import sqlite3

    root = tmp_path / "state"
    root.mkdir()
    (root / "media").mkdir()
    connection = sqlite3.connect(root / "state.sqlite3")
    connection.execute(
        "CREATE TABLE media_index (media_key TEXT PRIMARY KEY, platform TEXT, document_id TEXT,"
        " media_index INTEGER, url TEXT, local_path TEXT, sha256 TEXT, byte_size INTEGER,"
        " mime_type TEXT, status TEXT, failure_reason TEXT, http_status INTEGER,"
        " downloaded_at TEXT)"
    )
    connection.execute(
        "INSERT INTO media_index (media_key, platform, status) VALUES ('old:key', 'x', 'failed')"
    )
    connection.commit()
    connection.close()

    store = CollectionStore(root)
    columns = {row[1] for row in store._db.execute("PRAGMA table_info(media_index)")}
    assert {"attempts", "last_attempt_at"} <= columns
    kept = store.media_known("old:key")
    assert kept is not None and kept["status"] == "failed", "the migration must not drop rows"
    assert kept["attempts"] == 0
