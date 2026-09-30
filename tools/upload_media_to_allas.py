#!/usr/bin/env python3
"""Upload locally collected media objects to CSC Allas (S3-compatible).

Media URLs on the social platforms expire, so durable object storage is the
archive of record. This tool is idempotent and resumable: an object already
present in the bucket with a matching size is skipped, so re-running after an
interruption never re-uploads completed work and never loses a file.

Credentials are never taken from this file. The client uses the standard
boto3 credential chain (environment, shared ~/.aws/credentials written by
``allas-conf``, instance role). Endpoint/bucket come from flags or the
LACLAUGPT_S3_* environment variables.

Ceph-backed S3 (CSC Allas) rejects the streaming checksums that modern
botocore attaches by default, so ``request_checksum_calculation`` is forced to
``when_required``. Without it every PUT fails with MissingContentLength.

Usage:
    python tools/upload_media_to_allas.py --source-dir data/brazil26/media --dry-run
    python tools/upload_media_to_allas.py --source-dir data/brazil26/media --workers 8
"""
from __future__ import annotations

import argparse
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

DEFAULT_ENDPOINT = "https://a3s.fi"
CONTENT_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".json": "application/json",
    ".jsonl": "application/x-ndjson",
}


def build_client(endpoint: str, region: str):
    try:
        import boto3
        from botocore.config import Config
    except ImportError:  # pragma: no cover
        raise SystemExit("boto3 is required: pip install -e '.[distributed]'")

    return boto3.client(
        "s3",
        endpoint_url=endpoint or None,
        region_name=region or None,
        config=Config(
            signature_version="s3v4",
            request_checksum_calculation="when_required",
            s3={"addressing_style": "auto"},
            connect_timeout=15,
            read_timeout=300,
            retries={"max_attempts": 3, "mode": "standard"},
            max_pool_connections=64,
        ),
    )


def existing_objects(client, bucket: str, prefix: str) -> dict[str, int]:
    """Map object key -> size for everything already archived under prefix."""
    known: dict[str, int] = {}
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            known[obj["Key"]] = obj["Size"]
    return known


def content_type_for(path: Path) -> str:
    return CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream")


def collect_files(source_dir: Path, prefix: str) -> tuple[list[tuple[Path, str]], list[str]]:
    """Return (path, key) pairs, plus a warning list for basename collisions.

    The bucket convention is a flat ``<prefix>/<filename>`` layout, matching the
    objects already archived by the collector.
    """
    files = sorted(p for p in source_dir.rglob("*") if p.is_file())
    seen: dict[str, Path] = {}
    pairs: list[tuple[Path, str]] = []
    warnings: list[str] = []
    for path in files:
        key = f"{prefix}/{path.name}" if prefix else path.name
        clash = seen.get(key)
        if clash is not None and clash.stat().st_size != path.stat().st_size:
            warnings.append(f"basename collision: {key} ({clash}) vs ({path})")
            continue
        if clash is not None:
            continue
        seen[key] = path
        pairs.append((path, key))
    return pairs, warnings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source-dir", required=True, type=Path)
    parser.add_argument(
        "--bucket",
        default=os.environ.get("LACLAUGPT_S3_BUCKET", ""),
        help="target bucket (default: LACLAUGPT_S3_BUCKET)",
    )
    parser.add_argument(
        "--endpoint",
        default=os.environ.get("LACLAUGPT_S3_ENDPOINT_URL", DEFAULT_ENDPOINT),
    )
    parser.add_argument(
        "--region", default=os.environ.get("LACLAUGPT_S3_REGION", "regionOne")
    )
    parser.add_argument("--prefix", default="media", help="key prefix inside the bucket")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--limit", type=int, default=0, help="0 means no limit")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--verify-upload", action="store_true", help="HEAD each uploaded object afterwards"
    )
    args = parser.parse_args(argv)

    if not args.bucket:
        parser.error("--bucket or LACLAUGPT_S3_BUCKET is required")
    source_dir: Path = args.source_dir.expanduser().resolve()
    if not source_dir.is_dir():
        parser.error(f"source dir does not exist: {source_dir}")

    pairs, warnings = collect_files(source_dir, args.prefix)
    if args.limit > 0:
        pairs = pairs[: args.limit]
    total_bytes = sum(p.stat().st_size for p, _ in pairs)
    print(
        f"[allas] source={source_dir} files={len(pairs)} bytes={total_bytes / 1e9:.2f} GB "
        f"bucket={args.bucket} prefix={args.prefix}/",
        flush=True,
    )
    for warning in warnings[:10]:
        print(f"[allas] WARNING {warning}", flush=True)

    if args.dry_run:
        for path, key in pairs[:10]:
            print(f"[allas] would upload {key} ({path.stat().st_size} bytes)", flush=True)
        print(f"[allas] dry run: {len(pairs)} files, {total_bytes / 1e9:.2f} GB")
        return 0

    client = build_client(args.endpoint, args.region)
    print("[allas] listing existing objects ...", flush=True)
    known = existing_objects(client, args.bucket, args.prefix)
    print(f"[allas] already archived under {args.prefix}/: {len(known)}", flush=True)

    todo = [(p, k) for p, k in pairs if known.get(k) != p.stat().st_size]
    skipped = len(pairs) - len(todo)
    todo_bytes = sum(p.stat().st_size for p, _ in todo)
    print(
        f"[allas] skip={skipped} todo={len(todo)} todo_bytes={todo_bytes / 1e9:.2f} GB",
        flush=True,
    )
    if not todo:
        print("[allas] nothing to do; archive is current")
        return 0

    lock = threading.Lock()
    counters = {"done": 0, "failed": 0, "bytes": 0}
    failures: list[str] = []
    started = time.monotonic()

    def upload(item: tuple[Path, str]) -> None:
        path, key = item
        size = path.stat().st_size
        try:
            with path.open("rb") as handle:
                client.put_object(
                    Bucket=args.bucket,
                    Key=key,
                    Body=handle,
                    ContentLength=size,
                    ContentType=content_type_for(path),
                )
            if args.verify_upload:
                head = client.head_object(Bucket=args.bucket, Key=key)
                if int(head["ContentLength"]) != size:
                    raise RuntimeError(
                        f"size mismatch after upload: {head['ContentLength']} != {size}"
                    )
        except Exception as exc:  # noqa: BLE001
            with lock:
                counters["failed"] += 1
                failures.append(f"{key}: {type(exc).__name__}: {str(exc)[:120]}")
            return
        with lock:
            counters["done"] += 1
            counters["bytes"] += size
            if counters["done"] % 100 == 0 or counters["done"] == len(todo):
                rate = counters["bytes"] / max(time.monotonic() - started, 0.001) / 1e6
                print(
                    f"[allas] {counters['done']}/{len(todo)} "
                    f"({counters['bytes'] / 1e9:.2f} GB, {rate:.1f} MB/s, "
                    f"failed={counters['failed']})",
                    flush=True,
                )

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = [pool.submit(upload, item) for item in todo]
        for _ in as_completed(futures):
            pass

    elapsed = time.monotonic() - started
    print(
        f"[allas] finished: uploaded={counters['done']} failed={counters['failed']} "
        f"skipped={skipped} bytes={counters['bytes'] / 1e9:.2f} GB in {elapsed / 60:.1f} min",
        flush=True,
    )
    for failure in failures[:20]:
        print(f"[allas] FAILED {failure}", flush=True)
    return 1 if counters["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
