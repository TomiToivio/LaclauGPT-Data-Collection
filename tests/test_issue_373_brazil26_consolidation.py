"""Tests for the Brazil26 consolidation tool (issue #373).

The tool's whole job is to be trustworthy about *identity*: byte identity via
SHA-256, logical identity via (platform, document_id, media_index). These tests
build a tiny collection that exercises every case the real trees contain —
identical bytes under two names, one logical item with two distinct variants, a
file the index has never heard of, and an index hash that no longer matches.
"""

from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "brazil26"))
import consolidate as C  # noqa: E402


def _write(path: Path, data: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


@pytest.fixture()
def collection(tmp_path: Path) -> Path:
    root = tmp_path / "brasil"
    a = _write(root / "media" / "x_1.jpg", b"alpha")
    # Identical bytes, different name: one object, two references.
    _write(root / "media" / "tiktok_1.jpg", b"alpha")
    # Same logical item, genuinely different bytes: two variants, both kept.
    _write(root / "media" / "x_1_v2.jpg", b"beta")
    # A file the index does not know about.
    _write(root / "media" / "orphan.mp4", b"gamma")

    db = sqlite3.connect(root / "state.sqlite3")
    db.execute(
        "create table media_index (media_key text, platform text, document_id text, "
        "media_index integer, url text, local_path text, sha256 text, byte_size integer, "
        "mime_type text, status text, failure_reason text, http_status integer, downloaded_at text)"
    )
    rows = [
        ("x_1", "x", "d1", 1, "https://x/1", "media/x_1.jpg", a, 5, "image/jpeg", "ok", None, 200, "2026-09-10T00:00:00Z"),
        ("tiktok_1", "tiktok", "d2", 1, "https://tt/1", "media/tiktok_1.jpg", a, 5, "image/jpeg", "ok", None, 200, "2026-09-10T00:00:00Z"),
        # Deliberately wrong hash in the index: the file is authoritative.
        ("x_1_v2", "x", "d1", 1, "https://x/1", "media/x_1_v2.jpg", "0" * 64, 4, "image/jpeg", "ok", None, 200, "2026-09-11T00:00:00Z"),
    ]
    db.executemany("insert into media_index values (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    db.commit()
    db.close()

    norm = root / "normalized"
    norm.mkdir()
    with (norm / "x.jsonl").open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "platform": "x", "document_id": "d1", "author": "LulaOficial",
            "text": "soberania", "timestamp": "2026-09-10T00:00:00Z", "language": "pt",
        }) + "\n")
    return root


def test_manifest_hashes_every_file_and_matches_the_index(collection: Path) -> None:
    rows = C.build_manifest(collection)
    assert len(rows) == 4
    by_rel = {r.rel_path: r for r in rows}
    assert by_rel["media/x_1.jpg"].hash_matches_index
    assert by_rel["media/orphan.mp4"].in_index is False
    # The index hash is stale for this one; the file's real bytes win.
    assert by_rel["media/x_1_v2.jpg"].in_index
    assert not by_rel["media/x_1_v2.jpg"].hash_matches_index


def test_duplicate_bytes_collapse_but_logical_variants_are_kept(collection: Path) -> None:
    rows = C.build_manifest(collection)
    d = C.deduplicate(rows)
    assert d["physical_files"] == 4
    assert d["distinct_hashes"] == 3          # alpha, beta, gamma
    assert d["duplicate_files_collapsed"] == 1
    assert d["bytes_unique"] < d["bytes_total"]
    # x:d1:1 has two distinct files -> flagged, not silently collapsed.
    assert "x:d1:1" in d["variants"]
    assert len(d["variants"]["x:d1:1"]) == 2
    assert d["index_hash_mismatches"] == ["media/x_1_v2.jpg"]
    assert d["not_in_index"] == ["media/orphan.mp4"]


def test_object_keys_are_content_addressed(collection: Path) -> None:
    rows = C.build_manifest(collection)
    rows_by_rel = {r.rel_path: r for r in rows}
    keys = {r.rel_path: r.object_key for r in rows}
    assert keys["media/x_1.jpg"] == keys["media/tiktok_1.jpg"]
    assert keys["media/x_1.jpg"].endswith(".jpg")
    assert rows_by_rel["media/x_1.jpg"].sha256 in keys["media/x_1.jpg"]


def test_canonical_csv_joins_post_metadata_and_keeps_one_row_per_logical_item(collection: Path, tmp_path: Path) -> None:
    rows = C.build_manifest(collection)
    dedupe = C.deduplicate(rows)
    posts = C.read_posts(collection)
    out = tmp_path / "out"
    info = C.write_csvs(rows, dedupe, posts, out, "brazil26")

    with (out / "brazil26_canonical.csv").open(encoding="utf-8") as fh:
        canon = list(csv.DictReader(fh))
    # Three logical items: x:d1:1, tiktok:d2:1, and the orphan file.
    assert len(canon) == 3
    x_rows = [r for r in canon if r["canonical_id"] == "x:d1:1"]
    assert len(x_rows) == 1
    assert x_rows[0]["author"] == "LulaOficial"
    assert x_rows[0]["language"] == "pt"
    orphan = [r for r in canon if r["canonical_id"].startswith("file:")]
    assert orphan and orphan[0]["media_status"] == "unindexed_file"
    assert info["file_rows"] == 4


def test_inventory_reports_disagreement_between_index_and_disk(collection: Path) -> None:
    inv = C.inventory(collection)
    assert inv["indexed_media"] == 3
    assert inv["files_on_disk"] == 4
    assert inv["files_not_in_index"] == 1
    assert inv["database_present"] is True


def test_staging_creates_one_symlink_per_distinct_hash(collection: Path, tmp_path: Path) -> None:
    rows = C.build_manifest(collection)
    staging = tmp_path / "stage"
    n = C.stage_blobs(rows, rows, staging)
    assert n == 3
    links = [p for p in staging.rglob("*") if p.is_symlink()]
    assert len(links) == 3
    assert all(p.resolve().exists() for p in links)


def test_missing_database_is_not_fatal(tmp_path: Path) -> None:
    root = tmp_path / "bare"
    _write(root / "media" / "a.jpg", b"z")
    rows = C.build_manifest(root)
    assert len(rows) == 1 and rows[0].in_index is False


def test_basename_fallback_when_the_index_omits_the_subdirectory(tmp_path: Path) -> None:
    """The real TikTok rows store a bare filename in a per-collector subdirectory.

    Without the fallback those rows lose their platform and document id, which
    silently strips author and text from the canonical CSV.
    """
    root = tmp_path / "brasil"
    digest = _write(root / "media" / "tiktok_pyktok" / "@lula_video_1.mp4", b"tt")
    db = sqlite3.connect(root / "state.sqlite3")
    db.execute(
        "create table media_index (media_key text, platform text, document_id text, "
        "media_index integer, url text, local_path text, sha256 text, byte_size integer, "
        "mime_type text, status text, failure_reason text, http_status integer, downloaded_at text)"
    )
    db.execute("insert into media_index values (?,?,?,?,?,?,?,?,?,?,?,?,?)",
               ("tt1", "tiktok", "d9", 1, "https://tt/9", "@lula_video_1.mp4", digest, 2,
                "video/mp4", "ok", None, 200, "2026-09-10T00:00:00Z"))
    db.commit()
    db.close()

    rows = C.build_manifest(root)
    assert len(rows) == 1
    assert rows[0].in_index is True
    assert rows[0].path_match == "basename"
    assert rows[0].logical_key == "tiktok:d9:1"


def test_ambiguous_basename_is_not_matched(tmp_path: Path) -> None:
    """Two index rows with the same filename must not be guessed between."""
    root = tmp_path / "brasil"
    _write(root / "media" / "a" / "same.mp4", b"one")
    db = sqlite3.connect(root / "state.sqlite3")
    db.execute(
        "create table media_index (media_key text, platform text, document_id text, "
        "media_index integer, url text, local_path text, sha256 text, byte_size integer, "
        "mime_type text, status text, failure_reason text, http_status integer, downloaded_at text)"
    )
    for n, doc in (("k1", "d1"), ("k2", "d2")):
        db.execute("insert into media_index values (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (n, "x", doc, 1, "u", "elsewhere/same.mp4", "0" * 64, 3,
                    "video/mp4", "ok", None, 200, "2026-09-10T00:00:00Z"))
    db.commit()
    db.close()

    rows = C.build_manifest(root)
    assert rows[0].in_index is False
    assert rows[0].path_match == "none"
