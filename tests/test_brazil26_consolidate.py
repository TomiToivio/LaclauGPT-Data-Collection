"""Tests for the Brazil26 consolidation tool (#373).

Synthetic data only: a temporary SQLite state DB, a temporary media tree, and no network. The functions
under test are the ones that decide *what is duplicated*, *where an object goes* and *what counts as
missing* — getting those wrong is how an archive silently loses files or overwrites different content.
"""
from __future__ import annotations

import csv
import importlib.util
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("b26", ROOT / "scripts" / "brazil26_consolidate.py")
b26 = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(b26)


def make_state(tmp_path: Path, rows):
    db = tmp_path / "state.sqlite3"
    conn = sqlite3.connect(db)
    conn.execute(
        "create table media_index (media_key text, platform text, document_id text, media_index int,"
        " url text, local_path text, sha256 text, byte_size int, mime_type text, status text,"
        " failure_reason text, http_status int, downloaded_at text)"
    )
    conn.executemany("insert into media_index values (?,?,?,?,?,?,?,?,?,?,NULL,200,"
                     "'2026-09-09T15:34:23+00:00')", rows)
    conn.commit()
    conn.close()
    return db


def row(key, platform, doc, idx, path, sha, size, ctype="image/jpeg"):
    return (key, platform, doc, idx, "https://example.invalid/x", path, sha, size, ctype, "ok")


def test_object_key_is_content_addressed():
    a = b26.object_key("abc123", "media/x_1.mp4")
    b = b26.object_key("abc123", "media/other_name.mp4")
    assert a == b == "brazil26/videos/abc123.mp4"
    # different bytes, same name -> different keys
    assert b26.object_key("def456", "media/x_1.mp4") != a


def test_canonical_id_is_platform_scoped():
    assert b26.canonical_id("tiktok", "123") == "tiktok:123"
    assert b26.canonical_id("x", "123") != b26.canonical_id("tiktok", "123")


def test_resolve_local_path_handles_every_layout(tmp_path):
    (tmp_path / "media").mkdir()
    (tmp_path / "media" / "tiktok_pyktok").mkdir(parents=True)
    flat = tmp_path / "media" / "instagram_A_1.jpg"
    flat.write_bytes(b"x")
    nested = tmp_path / "media" / "tiktok_pyktok" / "@user_video_9.mp4"
    nested.write_bytes(b"y")

    assert b26.resolve_local_path(tmp_path, "media/instagram_A_1.jpg") == flat
    assert b26.resolve_local_path(tmp_path, "instagram_A_1.jpg") == flat
    # recorded without its subdirectory by the tiktok collector
    assert b26.resolve_local_path(tmp_path, "@user_video_9.mp4") == nested
    assert b26.resolve_local_path(tmp_path, "nope.jpg") is None


def test_build_manifests_dedupes_and_counts_missing(tmp_path):
    (tmp_path / "media").mkdir()
    (tmp_path / "media" / "a.jpg").write_bytes(b"same-bytes")
    (tmp_path / "media" / "b.jpg").write_bytes(b"same-bytes")
    (tmp_path / "media" / "c.jpg").write_bytes(b"other-bytes")
    sha_same = b26.sha256_of(tmp_path / "media" / "a.jpg")
    sha_other = b26.sha256_of(tmp_path / "media" / "c.jpg")

    db = make_state(tmp_path, [
        row("m1", "instagram", "D1", 1, "media/a.jpg", sha_same, 10),
        row("m2", "instagram", "D1", 2, "media/b.jpg", sha_same, 10),
        row("m3", "x", "D2", 1, "media/c.jpg", sha_other, 11),
        row("m4", "x", "D3", 1, "media/gone.jpg", "f" * 64, 99),
    ])
    canonical, files, report = b26.build_manifests(db, tmp_path)

    assert report["files"] == 4
    assert report["distinct_sha256"] == 2          # two identical files collapse
    assert report["canonical_records"] == 3        # D1, D2, D3
    assert report["missing_local"] == 1
    # one object key per distinct hash, shared by both copies
    keys = {f["sha256"]: f["object_key"] for f in files if f["status"] == "ok"}
    assert len(set(keys.values())) == 2
    d1 = next(c for c in canonical if c["canonical_id"] == "instagram:D1")
    assert d1["media_count"] == 2
    assert d1["media_status"] == "complete"
    d3 = next(c for c in canonical if c["canonical_id"] == "x:D3")
    assert d3["media_status"] == "partial 0/1"


def test_verify_detects_a_hash_mismatch(tmp_path):
    (tmp_path / "media").mkdir()
    p = tmp_path / "media" / "a.jpg"
    p.write_bytes(b"actual-bytes")
    db = make_state(tmp_path, [row("m1", "instagram", "D1", 1, "media/a.jpg", "0" * 64, 12)])

    _, files, report = b26.build_manifests(db, tmp_path, verify_hashes=True)
    assert report["hash_mismatch"] == 1
    assert files[0]["status"] == "hash_mismatch"
    # the manifest carries the real hash, never the wrong recorded one
    assert files[0]["sha256"] == b26.sha256_of(p)


def test_metadata_join_and_csv_columns(tmp_path):
    (tmp_path / "media").mkdir()
    (tmp_path / "media" / "a.jpg").write_bytes(b"bytes")
    (tmp_path / "normalized").mkdir()
    (tmp_path / "normalized" / "instagram.jsonl").write_text(json.dumps({
        "document_id": "D1", "platform": "instagram", "author": "someone",
        "timestamp": "2026-09-08T20:34:42Z", "source_url": "https://instagram.com/p/D1",
        "text": "line one\nline two", "hashtags": ["a", "b"],
    }) + "\n", encoding="utf-8")
    sha = b26.sha256_of(tmp_path / "media" / "a.jpg")
    db = make_state(tmp_path, [row("m1", "instagram", "D1", 1, "media/a.jpg", sha, 5)])

    canonical, files, _ = b26.build_manifests(db, tmp_path)
    out = tmp_path / "out"
    b26.write_csv(out / "c.csv", b26.CANONICAL_COLUMNS, canonical)
    b26.write_csv(out / "f.csv", b26.FILE_COLUMNS, files)

    got = next(csv.DictReader((out / "c.csv").open(encoding="utf-8")))
    assert got["author"] == "someone"
    assert got["hashtags"] == "a b"
    assert "\n" not in got["text"]           # a CSV row stays one row
    assert set(b26.CANONICAL_COLUMNS) <= set(got)
    assert len(list(csv.DictReader((out / "f.csv").open(encoding="utf-8")))) == 1


def test_dry_run_uploads_nothing(tmp_path, capsys):
    manifest = tmp_path / "f.csv"
    b26.write_csv(manifest, b26.FILE_COLUMNS, [{
        "canonical_id": "x:1", "platform": "x", "document_id": "1", "media_key": "m",
        "media_index": 1, "source_local_path": "media/a.jpg", "sha256": "a" * 64,
        "byte_size": 3, "content_type": "image/jpeg",
        "object_key": b26.object_key("a" * 64, "a.jpg"), "status": "ok",
    }])
    rc = b26.main(["upload", "--manifest", str(manifest), "--bucket", "b",
                   "--data-root", str(tmp_path), "--dry-run"])
    assert rc == 0
    assert "would put" in capsys.readouterr().out
