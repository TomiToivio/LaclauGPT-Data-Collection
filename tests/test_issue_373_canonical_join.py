"""Regression tests for the Brazil26 canonical join (#373).

Measured on the Helsinki deployment before the fix: 1,113 canonical rows, 0 with an author,
0 with a timestamp, while #376's report described the CSV as canonical. Two causes:

* ``load_posts`` read only flat keys, but canonical records nest the platform under
  ``source.platform`` and the id under ``source_native_ids.document_id``.
* This host's ``state.sqlite3`` stores the post *URL* in ``document_id``, and in a different
  URL form from the record (``/p/ABC`` in the index, ``/reel/ABC`` in the record).

After the fix, the same host yields 97 canonical rows (one per logical video), 97 with an
author and 91 with text.
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest

MODULE = Path(__file__).resolve().parent.parent / "scripts" / "brazil26_consolidate.py"


@pytest.fixture(scope="module")
def tool():
    spec = importlib.util.spec_from_file_location("brazil26_consolidate_main", MODULE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_record(root: Path, platform: str, doc: str, url: str, author: str, text: str) -> None:
    (root / "normalized").mkdir(parents=True, exist_ok=True)
    record = {
        "source_url": url,
        "source_native_ids": {"document_id": doc},
        "source": {"platform": platform, "author": author, "created_at": "2026-09-07T18:45:08Z"},
        "content": {"text": text},
        "raw_capture": {"payload": {"legacy": {"full_text": text}}},
    }
    with (root / "normalized" / f"{platform}.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")


def _write_index(root: Path, rows: list[dict]) -> None:
    conn = sqlite3.connect(root / "state.sqlite3")
    conn.execute(
        "create table media_index (media_key text, platform text, document_id text,"
        " media_index integer, url text, local_path text, sha256 text, byte_size integer,"
        " mime_type text, status text, downloaded_at text)"
    )
    conn.executemany(
        "insert into media_index values (:media_key,:platform,:document_id,:media_index,:url,"
        ":local_path,:sha256,:byte_size,:mime_type,:status,:downloaded_at)", rows)
    conn.commit()
    conn.close()


def test_nested_canonical_schema_is_read(tool, tmp_path: Path) -> None:
    root = tmp_path / "data"
    _write_record(root, "instagram", "ABC123", "https://www.instagram.com/reel/ABC123",
                  "someone", "caption")
    posts = tool.load_posts(root / "normalized")
    assert ("instagram", "ABC123") in posts
    assert posts[("instagram", "ABC123")]["author"] == "someone"
    assert posts[("instagram", "ABC123")]["text"] == "caption"
    assert posts[("instagram", "ABC123")]["timestamp"] == "2026-09-07T18:45:08Z"


def test_flat_legacy_schema_still_read(tool, tmp_path: Path) -> None:
    root = tmp_path / "data"
    (root / "normalized").mkdir(parents=True)
    (root / "normalized" / "x.jsonl").write_text(
        json.dumps({"platform": "x", "document_id": "42", "author": "legacy",
                    "timestamp": "2026-01-01T00:00:00Z", "text": "hi"}) + "\n",
        encoding="utf-8")
    posts = tool.load_posts(root / "normalized")
    assert posts[("x", "42")]["author"] == "legacy"


def test_url_shaped_document_id_joins_to_its_post(tool, tmp_path: Path) -> None:
    root = tmp_path / "data"
    _write_record(root, "instagram", "ABC123", "https://www.instagram.com/reel/ABC123",
                  "someone", "caption")
    media = root / "media" / "brazil26_instagram_0.jpg"
    media.parent.mkdir(parents=True)
    media.write_bytes(b"jpeg")
    _write_index(root, [{
        "media_key": "m1", "platform": "instagram",
        "document_id": "https://www.instagram.com/p/ABC123",
        "media_index": 0, "url": "https://www.instagram.com/p/ABC123",
        "local_path": media.relative_to(root).as_posix(),
        "sha256": "0" * 64, "byte_size": 4, "mime_type": "image/jpeg",
        "status": "downloaded", "downloaded_at": "2026-10-09T10:00:00Z",
    }])

    canonical, files, report = tool.build_manifests(root / "state.sqlite3", root)
    assert len(files) == 1
    assert len(canonical) == 1
    row = canonical[0]
    assert row["document_id"] == "ABC123"
    assert row["canonical_id"] == "instagram:ABC123"
    assert row["author"] == "someone"
    assert row["post_timestamp"] == "2026-09-07T18:45:08Z"
    assert row["text"] == "caption"
    assert report["canonical_records"] == 1
