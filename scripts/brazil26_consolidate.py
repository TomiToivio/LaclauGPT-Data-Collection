#!/usr/bin/env python3
"""Consolidate the Brazil26 corpus and archive it in CSC Allas (#373).

The corpus lives in two places on a collection host: a media tree (images and video) and a metadata
index that already carries a SHA-256 for every file. This tool turns that into one shareable dataset:

    brazil26/videos/<sha256>.<ext>   one object per distinct byte sequence, whatever machine it came from
    brazil26/metadata/brazil26_canonical.csv    one row per logical video
    brazil26/manifests/brazil26_files.csv       one row per media file, linked by canonical id

Why content-addressed keys: the issue requires that identical bytes occupy one object even when several
machines collected them, and that distinct versions stay traceable. A hash key gives both for free — two
copies of the same file cannot collide, and two different files cannot merge.

Idempotency: an object is skipped when it already exists with the same size *and* the same `sha256`
metadata. Size alone is not enough (that was the earlier uploader's rule); two different files can share a
size, and re-uploading over them would be destructive.

Commands:
    inventory  build the canonical CSV and file manifest from the state DB + media tree
    upload     push the distinct files to Allas (idempotent, resumable, --dry-run)
    validate   re-list the bucket and reconcile it against the manifest

No credentials are read here: boto3's normal chain (environment or ~/.aws/credentials from `allas-conf`)
supplies them, and the bucket/endpoint come from flags or LACLAUGPT_S3_* variables.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

DATASET = "brazil26"
CANONICAL_COLUMNS = [
    "canonical_id", "dataset", "platform", "document_id", "url", "author",
    "post_timestamp", "collected_at", "text", "hashtags", "media_count",
    "media_status", "media_sha256", "media_bytes", "object_key", "source_local_path",
]
FILE_COLUMNS = [
    "canonical_id", "platform", "document_id", "media_key", "media_index",
    "source_local_path", "sha256", "byte_size", "content_type", "object_key", "status",
]
CONTENT_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
                 ".webp": "image/webp", ".gif": "image/gif", ".mp4": "video/mp4",
                 ".mov": "video/quicktime", ".webm": "video/webm", ".mp3": "audio/mpeg",
                 ".m4a": "audio/mp4"}


def canonical_id(platform: str, document_id: str) -> str:
    return f"{platform}:{document_id}"


def object_key(sha256: str, path: str | Path) -> str:
    """One key per distinct byte sequence, extension preserved for readers."""
    ext = Path(path).suffix.lower()
    return f"{DATASET}/videos/{sha256}{ext}"


def content_type_for(path: str | Path) -> str:
    return CONTENT_TYPES.get(Path(path).suffix.lower(), "application/octet-stream")


def resolve_local_path(data_root: Path, local_path: str) -> Path | None:
    """Find a media file, tolerating the several layouts the collectors produced.

    The state DB records some TikTok files without their subdirectory, so a bare join is not enough.
    Returning None (rather than a guess) keeps missing files countable instead of silently skipped.
    """
    p = Path(local_path)
    candidates = [p] if p.is_absolute() else [
        data_root / p,
        data_root / "media" / p.name,
        data_root / "media" / "tiktok_pyktok" / p.name,
    ]
    for c in candidates:
        if c.is_file():
            return c
    return None


def sha256_of(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def load_posts(normalized_dir: Path) -> dict[tuple[str, str], dict]:
    """document_id -> metadata, per platform, from the normalized JSONL."""
    posts: dict[tuple[str, str], dict] = {}
    if not normalized_dir.is_dir():
        return posts
    for f in sorted(normalized_dir.glob("*.jsonl")):
        with f.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                platform = rec.get("platform") or f.stem
                doc = rec.get("document_id")
                if doc:
                    posts[(platform, doc)] = rec
    return posts


def build_manifests(state_db: Path, data_root: Path, *, verify_hashes: bool = False):
    """Return (canonical rows, file rows, report) from the state DB and the media tree."""
    conn = sqlite3.connect(f"file:{state_db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    files: list[dict] = []
    missing: list[str] = []
    hash_mismatch: list[str] = []
    for row in conn.execute(
        "select media_key, platform, document_id, media_index, url, local_path, sha256,"
        " byte_size, mime_type, status, downloaded_at from media_index"
    ):
        rec = dict(row)
        path = resolve_local_path(data_root, rec["local_path"] or "")
        cid = canonical_id(rec["platform"], rec["document_id"])
        entry = {
            "canonical_id": cid, "platform": rec["platform"], "document_id": rec["document_id"],
            "media_key": rec["media_key"], "media_index": rec["media_index"],
            "source_local_path": rec["local_path"],
            "downloaded_at": rec["downloaded_at"] or "",
            "sha256": rec["sha256"] or "", "byte_size": rec["byte_size"] or 0,
            "content_type": rec["mime_type"] or content_type_for(rec["local_path"] or ""),
            "object_key": object_key(rec["sha256"], rec["local_path"] or "") if rec["sha256"] else "",
            "status": "ok" if path else "missing_local",
        }
        if path is None:
            missing.append(rec["media_key"])
        elif verify_hashes:
            actual = sha256_of(path)
            if actual != rec["sha256"]:
                hash_mismatch.append(rec["media_key"])
                entry["status"] = "hash_mismatch"
                entry["sha256"] = actual
                entry["object_key"] = object_key(actual, path)
            elif path.stat().st_size != rec["byte_size"]:
                entry["status"] = "size_mismatch"
        files.append(entry)
    conn.close()

    posts = load_posts(data_root / "normalized")
    by_cid: dict[str, list[dict]] = {}
    for f in files:
        by_cid.setdefault(f["canonical_id"], []).append(f)

    canonical: list[dict] = []
    for cid, group in sorted(by_cid.items()):
        platform, doc = cid.split(":", 1)
        meta = posts.get((platform, doc), {})
        ok = [g for g in group if g["status"] == "ok"]
        primary = ok[0] if ok else group[0]
        canonical.append({
            "canonical_id": cid, "dataset": DATASET, "platform": platform, "document_id": doc,
            "url": meta.get("source_url", ""), "author": meta.get("author", ""),
            "post_timestamp": meta.get("timestamp", ""), "collected_at": primary.get("downloaded_at", ""),
            "text": (meta.get("text") or "").replace("\n", " ")[:2000],
            "hashtags": " ".join(meta.get("hashtags") or []),
            "media_count": len(group),
            "media_status": "complete" if len(ok) == len(group) else f"partial {len(ok)}/{len(group)}",
            "media_sha256": primary["sha256"], "media_bytes": primary["byte_size"],
            "object_key": primary["object_key"], "source_local_path": primary["source_local_path"],
        })

    report = {
        "dataset": DATASET,
        "files": len(files),
        "canonical_records": len(canonical),
        # only files we actually hold can become objects; a missing local file must not
        # inflate the archive target or the validation denominator
        "distinct_sha256": len({f["sha256"] for f in files if f["sha256"] and f["status"] == "ok"}),
        "bytes": sum(f["byte_size"] for f in files if f["sha256"]),
        "missing_local": len(missing),
        "hash_mismatch": len(hash_mismatch),
        "platforms": {p: sum(1 for f in files if f["platform"] == p)
                      for p in sorted({f["platform"] for f in files})},
        "missing_examples": missing[:10],
    }
    return canonical, files, report


def write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def _client(endpoint: str | None):
    import boto3
    from botocore.config import Config
    return boto3.client(
        "s3",
        endpoint_url=endpoint or os.environ.get("LACLAUGPT_S3_ENDPOINT_URL") or "https://a3s.fi",
        config=Config(signature_version="s3v4", request_checksum_calculation="when_required",
                      retries={"max_attempts": 5, "mode": "standard"}),
    )


def cmd_inventory(args) -> int:
    if not str(args.data_root):
        raise SystemExit("error: set $BRAZIL26_ROOT or pass --data-root")
    state_db = Path(args.state_db) if args.state_db else Path(args.data_root) / "state.sqlite3"
    canonical, files, report = build_manifests(
        state_db, Path(args.data_root), verify_hashes=args.verify)
    write_csv(Path(args.out) / "brazil26_canonical.csv", CANONICAL_COLUMNS, canonical)
    write_csv(Path(args.out) / "brazil26_files.csv", FILE_COLUMNS, files)
    (Path(args.out) / "inventory.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


def cmd_upload(args) -> int:
    rows = list(csv.DictReader(Path(args.manifest).open(encoding="utf-8")))
    todo = [r for r in rows if r.get("sha256") and r.get("status") == "ok"]
    # one upload per distinct byte sequence
    unique: dict[str, dict[str, object]] = {}
    for r in todo:
        unique.setdefault(r["sha256"], {"key": r["object_key"], "size": int(r["byte_size"]),
                                        "path": r["source_local_path"]})
    print(f"[upload] files={len(todo)} distinct={len(unique)} "
          f"bytes={sum(int(v['size']) for v in unique.values()) / 1e9:.2f} GB")
    if args.dry_run:
        for sha, v in list(unique.items())[:10]:
            print(f"[upload] would put {v['key']} ({v['size']} bytes)")
        return 0

    client = _client(args.endpoint)
    lock = threading.Lock()
    stats = {"uploaded": 0, "skipped": 0, "failed": 0, "bytes": 0}
    failures: list[str] = []

    def work(item):
        sha, meta = item
        key = str(meta["key"])
        size = int(meta["size"])
        path = resolve_local_path(Path(args.data_root), str(meta["path"]))
        if path is None:
            with lock:
                stats["failed"] += 1
                failures.append(f"{key}: local file missing")
            return
        try:
            head = client.head_object(Bucket=args.bucket, Key=key)
            same = int(head["ContentLength"]) == size and \
                (head.get("Metadata") or {}).get("sha256") == sha
            if same:
                with lock:
                    stats["skipped"] += 1
                return
            if not args.overwrite and int(head["ContentLength"]) != size:
                with lock:
                    stats["failed"] += 1
                    failures.append(f"{key}: exists with different size, not overwriting")
                return
        except Exception:
            pass  # absent: upload it
        try:
            with path.open("rb") as fh:
                client.put_object(Bucket=args.bucket, Key=key, Body=fh, ContentLength=size,
                                  ContentType=content_type_for(path),
                                  Metadata={"sha256": sha, "dataset": DATASET})
            with lock:
                stats["uploaded"] += 1
                stats["bytes"] += size
        except Exception as exc:  # noqa: BLE001
            with lock:
                stats["failed"] += 1
                failures.append(f"{key}: {type(exc).__name__}: {str(exc)[:120]}")

    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(work, item) for item in unique.items()]
        for i, _ in enumerate(as_completed(futures), 1):
            if i % 25 == 0 or i == len(futures):
                print(f"[upload] {i}/{len(futures)} uploaded={stats['uploaded']} "
                      f"skipped={stats['skipped']} failed={stats['failed']}", flush=True)
    print(f"[upload] done in {(time.monotonic() - started) / 60:.1f} min: {stats}")
    for f in failures[:20]:
        print(f"[upload] FAIL {f}")
    return 1 if stats["failed"] else 0


def cmd_validate(args) -> int:
    rows = list(csv.DictReader(Path(args.manifest).open(encoding="utf-8")))
    want = {r["object_key"]: int(r["byte_size"] or 0) for r in rows if r.get("object_key")}
    client = _client(args.endpoint)
    seen: dict[str, int] = {}
    token = None
    while True:
        kw = {"Bucket": args.bucket, "Prefix": f"{DATASET}/videos/"}
        if token:
            kw["ContinuationToken"] = token
        resp = client.list_objects_v2(**kw)
        for obj in resp.get("Contents", []):
            seen[obj["Key"]] = int(obj["Size"])
        if not resp.get("IsTruncated"):
            break
        token = resp.get("NextContinuationToken")
    missing = sorted(set(want) - set(seen))
    extra = sorted(set(seen) - set(want))
    size_bad = sorted(k for k in want if k in seen and seen[k] != want[k])
    report = {
        "expected_objects": len(want), "present_objects": len(seen),
        "expected_bytes": sum(want.values()), "present_bytes": sum(seen.values()),
        "missing": len(missing), "extra": len(extra), "size_mismatch": len(size_bad),
        "sample_missing": missing[:5], "sample_extra": extra[:5],
    }
    print(json.dumps(report, indent=2))
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0 if not (missing or extra or size_bad) else 1


def _root_default() -> str:
    """Collection root from the environment, never a hardcoded home directory.

    A machine-specific path in a public repository is a policy violation and is
    useless to anyone else running this: the root belongs to the host, not to the
    tool.
    """
    return os.environ.get("BRAZIL26_ROOT", "")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Brazil26 consolidation and Allas archive (#373)")
    sub = p.add_subparsers(dest="cmd", required=True)

    inv = sub.add_parser("inventory", help="build canonical CSV + file manifest")
    inv.add_argument("--state-db", default="", help="default: $BRAZIL26_ROOT/state.sqlite3")
    inv.add_argument("--data-root", default=_root_default(), help="default: $BRAZIL26_ROOT")
    inv.add_argument("--out", default="out/brazil26")
    inv.add_argument("--verify", action="store_true", help="recompute every SHA-256")
    inv.set_defaults(func=cmd_inventory)

    up = sub.add_parser("upload", help="upload distinct files to Allas")
    up.add_argument("--manifest", required=True)
    up.add_argument("--data-root", default=_root_default(), help="default: $BRAZIL26_ROOT")
    up.add_argument("--bucket", default=os.environ.get("LACLAUGPT_S3_BUCKET", ""))
    up.add_argument("--endpoint", default=None)
    up.add_argument("--workers", type=int, default=8)
    up.add_argument("--dry-run", action="store_true")
    up.add_argument("--overwrite", action="store_true")
    up.set_defaults(func=cmd_upload)

    val = sub.add_parser("validate", help="reconcile the bucket against the manifest")
    val.add_argument("--manifest", required=True)
    val.add_argument("--bucket", default=os.environ.get("LACLAUGPT_S3_BUCKET", ""))
    val.add_argument("--endpoint", default=None)
    val.add_argument("--out", default=None)
    val.set_defaults(func=cmd_validate)

    args = p.parse_args(argv)
    if args.cmd in ("upload", "validate") and not args.bucket:
        print("error: set --bucket or LACLAUGPT_S3_BUCKET", file=sys.stderr)
        return 2
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
