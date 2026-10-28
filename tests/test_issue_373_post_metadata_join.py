"""Regression tests for the Brazil26 post-metadata join (#373).

Two defects were measured on the Helsinki deployment and are pinned here:

1. ``read_posts`` only understood the flat record schema, while the canonical records nest
   the platform under ``source.platform`` and the id under ``source_native_ids.document_id``.
   The join silently missed every post, so the "canonical" CSV shipped 1,113 rows with zero
   author or timestamp and still claimed to be canonical.
2. This host's ``state.sqlite3`` stores the post **URL** in ``document_id``, and in a
   different form from the records (``/p/`` in the index, ``/reel/`` in the record). Exact
   URL matching therefore misses too; the native code has to be extracted and matched.

Together they are worth 1,108 of 1,113 rows on this deployment.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest

MODULE = Path(__file__).resolve().parent.parent / "scripts" / "brazil26" / "consolidate.py"


@pytest.fixture(scope="module")
def tool():
    spec = importlib.util.spec_from_file_location("brazil26_consolidate_tested", MODULE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_record(root: Path, platform: str, doc: str, url: str, author: str) -> None:
    (root / "normalized").mkdir(parents=True, exist_ok=True)
    record = {
        "source_url": url,
        "source_native_ids": {"document_id": doc},
        "source": {"platform": platform, "author": author,
                   "created_at": "2026-09-07T18:45:08Z"},
        "raw_capture": {"payload": {"desc": "caption text"}},
    }
    with (root / "normalized" / f"{platform}.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")


def _write_index(root: Path, rows: list[dict]) -> None:
    conn = sqlite3.connect(root / "state.sqlite3")
    conn.execute(
        "create table media_index (local_path text, platform text, document_id text,"
        " media_index text, byte_size integer)"
    )
    conn.executemany(
        "insert into media_index values (:local_path, :platform, :document_id, :media_index, :byte_size)",
        rows,
    )
    conn.commit()
    conn.close()


def test_nested_canonical_schema_is_read(tool, tmp_path: Path) -> None:
    root = tmp_path / "data"
    _write_record(root, "instagram", "ABC123", "https://www.instagram.com/reel/ABC123", "someone")
    posts = tool.read_posts(root)
    assert ("instagram", "ABC123") in posts
    assert posts[("instagram", "ABC123")]["author"] == "someone"
    assert posts[("instagram", "ABC123")]["timestamp"] == "2026-09-07T18:45:08Z"


def test_flat_legacy_schema_still_read(tool, tmp_path: Path) -> None:
    root = tmp_path / "data"
    (root / "normalized").mkdir(parents=True)
    (root / "normalized" / "x.jsonl").write_text(
        json.dumps({"platform": "x", "document_id": "42", "author": "legacy",
                    "timestamp": "2026-01-01T00:00:00Z", "text": "hi"}) + "\n",
        encoding="utf-8",
    )
    posts = tool.read_posts(root)
    assert posts[("x", "42")]["author"] == "legacy"


def test_url_document_id_in_a_different_url_form_still_joins(tool, tmp_path: Path) -> None:
    """Index says ``/p/ABC123``, the record says ``/reel/ABC123``: same post."""
    root = tmp_path / "data"
    url = "https://www.instagram.com/reel/ABC123"
    _write_record(root, "instagram", "ABC123", url, "someone")
    token = hashlib.sha256(url.encode()).hexdigest()[:16]
    media_dir = root / "media" / "inst"
    media_dir.mkdir(parents=True)
    media = media_dir / f"brazil26_instagram_{token}_0.jpg"
    media.write_bytes(b"jpeg")
    _write_index(root, [{
        "local_path": media.relative_to(root).as_posix(),
        "platform": "instagram",
        "document_id": "https://www.instagram.com/p/ABC123",
        "media_index": "0",
        "byte_size": 4,
    }])

    rows = tool.build_manifest(root, workers=1, urls=tool.read_post_urls(root))
    assert len(rows) == 1
    assert rows[0].document_id == "ABC123"
    assert (rows[0].platform, rows[0].document_id) in tool.read_posts(root)
