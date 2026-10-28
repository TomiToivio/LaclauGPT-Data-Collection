"""Synthetic, filesystem-only checks for issue #373. No Allas credentials needed."""
import csv
import json
from pathlib import Path

from scripts.brazil26_reconcile_offline import file_hash, inventory


def _csv(path: Path, records: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "platform", "post_id", "source_url", "creator", "metadata_id",
            "caption", "media_path",
        ])
        writer.writeheader()
        writer.writerows(records)


def test_multihost_identical_files_collapse_and_conflicts_preserved(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    (a / "one.mp4").write_bytes(b"video")
    (b / "copy.mp4").write_bytes(b"video")
    _csv(a / "meta.csv", [{"platform": "TikTok", "post_id": "42",
        "creator": "account_a", "caption": "alpha", "metadata_id": "a",
        "media_path": "one.mp4", "source_url": "https://example.org/42?tracking=1"}])
    _csv(b / "meta.csv", [{"platform": "tiktok", "post_id": "42",
        "creator": "account_a", "caption": "beta", "metadata_id": "b",
        "media_path": "copy.mp4", "source_url": "https://example.org/42"}])
    output = tmp_path / "result"
    report = inventory([("pc", a / "meta.csv"), ("wsl", b / "meta.csv")], output)
    assert report["logical_videos"] == 1
    assert report["unique_file_hashes"] == 1
    assert report["duplicate_media_references"] == 1
    assert report["conflicts"] == 1
    assert report["upload_verified"] is False
    with (output / "canonical_metadata.csv").open() as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["canonical_id"] == "tiktok:42"
    assert rows[0]["variant_count"] == "1"
    assert rows[0]["media_status"] == "pending_upload"
    assert set(rows[0]["source_hosts"].split(";")) == {"pc", "wsl"}
    conflicts = json.loads((output / "conflicts.json").read_text())
    assert conflicts[0]["values"] == ["alpha", "beta"]


def test_different_versions_preserved_and_missing_media_flagged(tmp_path):
    folder = tmp_path / "host"
    folder.mkdir()
    (folder / "first.mp4").write_bytes(b"first")
    (folder / "second.mp4").write_bytes(b"second")
    _csv(folder / "meta.csv", [
        {"platform": "x", "post_id": "7", "media_path": "first.mp4"},
        {"platform": "x", "post_id": "7", "media_path": "second.mp4"},
        {"platform": "x", "post_id": "8", "media_path": "missing.mp4"},
        {"platform": "x", "post_id": "9", "media_path": "../outside.mp4"},
    ])
    out = tmp_path / "out"
    result = inventory([("host", folder / "meta.csv")], out)
    assert result["logical_videos"] == 3
    assert result["media_variants"] == 2
    assert result["exceptions"] == 2
    with (out / "canonical_metadata.csv").open() as handle:
        records = {r["canonical_id"]: r for r in csv.DictReader(handle)}
    assert records["x:7"]["variant_count"] == "2"
    assert records["x:8"]["media_status"] == "missing_media"


def test_hash_streams_full_file(tmp_path):
    file = tmp_path / "blob"
    file.write_bytes(b"0" * (1024 * 1024 + 3))
    sha, size = file_hash(file)
    assert len(sha) == 64 and size == 1024 * 1024 + 3
