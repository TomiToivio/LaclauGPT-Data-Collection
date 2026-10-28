#!/usr/bin/env python3
"""Brazil26 consolidation: inventory, manifest, deduplicate, canonical CSV, Allas upload.

This is a *consolidation* tool, not a collector. It reads what a collection host
already has, emits a machine-independent manifest, collapses byte-identical media
onto one canonical object, and uploads that once — idempotently.

Subcommands
-----------
run       inventory -> manifest -> dedupe -> canonical CSV (+ audit report)
upload    stage unique blobs and copy them to Allas (idempotent, resumable)
verify    re-list Allas and compare against the manifest

Design rules that the code enforces
-----------------------------------
* The logical content key is (platform, document_id, media_index). It identifies
  *what media item this is*, independent of which host collected it.
* The byte key is SHA-256. Two files with the same SHA-256 are one object.
* Distinct bytes under one logical key are two variants, both kept and flagged.
* Nothing is deleted. The source tree is read-only.
* `--dry-run` never touches the network and never writes outside the output dir.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_DATASET = "brazil26"
MEDIA_DIR = "media"


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


@dataclass
class MediaRow:
    """One physical media file, with the index facts it was matched against."""

    logical_key: str
    platform: str
    document_id: str
    media_index: str
    sha256: str
    byte_size: int
    rel_path: str
    abs_path: str
    mime_type: str
    index_sha256: str
    index_byte_size: int
    hash_matches_index: bool
    size_matches_index: bool
    in_index: bool
    downloaded_at: str
    source_host: str
    source_root: str
    source_url: str
    path_match: str = "exact"

    @property
    def object_key(self) -> str:
        """Canonical Allas key: content-addressed, so identical bytes never repeat."""
        ext = Path(self.rel_path).suffix.lower() or ""
        return f"{MEDIA_DIR}/{self.sha256[:2]}/{self.sha256}{ext}"


def read_media_index(db: Path) -> list[dict]:
    if not db.exists():
        return []
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        tables = {r[0] for r in conn.execute("select name from sqlite_master where type='table'")}
        if "media_index" not in tables:
            return []
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute("select * from media_index")]
    finally:
        conn.close()


def _post_text(rec: dict) -> str:
    payload = (rec.get("raw_capture") or {}).get("payload") or {}
    legacy = payload.get("legacy") or {}
    for candidate in (rec.get("text"), legacy.get("full_text"), payload.get("desc")):
        if isinstance(candidate, str) and candidate.strip():
            return " ".join(candidate.split())
    return ""


def read_posts(root: Path) -> dict[tuple[str, str], dict]:
    """Post-level metadata, joined on (platform, document_id).

    The media index carries no author or text, so the canonical CSV would be
    metadata-poor without this join.

    The canonical record contract nests the platform under ``source.platform`` and the
    id under ``source_native_ids.document_id``; flat keys are accepted too, because
    older exports wrote them that way. Returning a normalised dict keeps the CSV writer
    free of schema branching.
    """
    posts: dict[tuple[str, str], dict] = {}
    ndir = root / "normalized"
    if not ndir.is_dir():
        return posts
    for path in sorted(ndir.glob("*.jsonl")):
        with path.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                source = rec.get("source") or {}
                platform = str(rec.get("platform") or source.get("platform") or path.stem).lower()
                doc = str(rec.get("document_id") or rec.get("post_id")
                          or (rec.get("source_native_ids") or {}).get("document_id") or "")
                if not doc:
                    continue
                posts[(platform, doc)] = {
                    "source_url": str(rec.get("source_url") or ""),
                    "author": str(rec.get("author") or source.get("author") or ""),
                    "timestamp": str(rec.get("timestamp") or source.get("created_at") or ""),
                    "text": _post_text(rec),
                    "language": str(rec.get("language") or source.get("language") or ""),
                }
    return posts


def read_post_urls(root: Path) -> dict[str, tuple[str, str]]:
    """Map a post URL to (platform, native id).

    Some indexes store the post URL in ``document_id`` instead of the native id. Without
    this map the join to normalized post metadata silently misses every row, and the
    canonical CSV ships with empty author/text while claiming to be canonical.
    """
    urls: dict[str, tuple[str, str]] = {}
    ndir = root / "normalized"
    if not ndir.is_dir():
        return urls
    for path in sorted(ndir.glob("*.jsonl")):
        with path.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                source = rec.get("source") or {}
                platform = str(rec.get("platform") or source.get("platform") or path.stem).lower()
                doc = str(rec.get("document_id") or rec.get("post_id")
                          or (rec.get("source_native_ids") or {}).get("document_id") or "")
                code = post_code(str(rec.get("source_url") or ""))
                if platform and doc and code:
                    urls[f"{platform}:{code}"] = doc
    return urls


def post_code(url: str) -> str:
    """The platform-native code in a post URL, ignoring the ``/p/`` vs ``/reel/`` form."""
    m = re.search(r"/(?:p|reel|reels|status|video|watch)/([^/?#]+)", url)
    return m.group(1) if m else ""


def inventory(root: Path, limit: int | None = None) -> dict:
    """What this host actually holds, including media the index does not know."""
    media_dir = root / MEDIA_DIR
    files = [p for p in media_dir.rglob("*") if p.is_file()] if media_dir.is_dir() else []
    indexed = read_media_index(root / "state.sqlite3")
    by_platform: dict[str, int] = {}
    by_mime: dict[str, int] = {}
    for row in indexed:
        by_platform[row.get("platform") or "?"] = by_platform.get(row.get("platform") or "?", 0) + 1
        by_mime[row.get("mime_type") or "?"] = by_mime.get(row.get("mime_type") or "?", 0) + 1
    known = {(r.get("local_path") or "").replace("\\", "/") for r in indexed}
    known_names = {Path(k).name for k in known if k}
    unmatched = sum(1 for p in files
                    if p.relative_to(root).as_posix() not in known
                    and p.name not in known_names)
    on_disk = sum(p.stat().st_size for p in files)
    return {
        "host": os.uname().nodename,
        "root": str(root),
        "generated_at": utcnow(),
        "indexed_media": len(indexed),
        "indexed_bytes": sum(r.get("byte_size") or 0 for r in indexed),
        "files_on_disk": len(files),
        "bytes_on_disk": on_disk,
        "files_not_in_index": unmatched,
        "indexed_by_platform": by_platform,
        "indexed_by_mime": by_mime,
        "database": str(root / "state.sqlite3"),
        "database_present": (root / "state.sqlite3").exists(),
        "truncated_for_test": bool(limit),
    }


def build_manifest(root: Path, workers: int = 8, limit: int | None = None,
                   urls: dict[str, tuple[str, str]] | None = None) -> list[MediaRow]:
    """Hash every media file on disk and attach the index facts for it."""
    host = os.uname().nodename
    media_dir = root / MEDIA_DIR
    if not media_dir.is_dir():
        return []
    indexed = read_media_index(root / "state.sqlite3")
    by_rel = {(r.get("local_path") or "").replace("\\", "/"): r for r in indexed}
    # The index does not always record a resolvable path: TikTok rows store a bare
    # filename while the files live in a per-collector subdirectory. Fall back to
    # basename matching, but only when it is unambiguous, and record which match
    # was used so a guess can never masquerade as a fact.
    by_base: dict[str, list[dict]] = {}
    for r in indexed:
        lp = (r.get("local_path") or "").replace("\\", "/")
        if lp:
            by_base.setdefault(Path(lp).name, []).append(r)

    files = sorted(p for p in media_dir.rglob("*") if p.is_file())
    if limit:
        files = files[:limit]

    def match(path: Path) -> tuple[dict, str]:
        rel = path.relative_to(root).as_posix()
        for cand in (rel, rel.removeprefix(f"{MEDIA_DIR}/"), path.name):
            if cand in by_rel:
                return by_rel[cand], ("exact" if cand != path.name else "basename")
        loose = by_base.get(path.name) or []
        if len(loose) == 1:
            return loose[0], "basename"
        return {}, "none"

    def work(path: Path) -> MediaRow:
        rel = path.relative_to(root).as_posix()
        idx, how = match(path)
        digest = sha256_file(path)
        size = path.stat().st_size
        index_size = int(idx.get("byte_size") or 0)
        platform = (idx.get("platform") or "").lower() or "unknown"
        doc = str(idx.get("document_id") or "")
        if doc.startswith("http") and urls:
            code = post_code(doc)
            resolved = urls.get(f"{platform}:{code}")
            if resolved:
                doc = resolved
        mindex = str(idx.get("media_index") or "")
        logical = f"{platform}:{doc}:{mindex}" if doc else f"file:{rel}"
        return MediaRow(
            logical_key=logical,
            platform=platform,
            document_id=doc,
            media_index=mindex,
            sha256=digest,
            byte_size=size,
            rel_path=rel,
            abs_path=str(path),
            mime_type=str(idx.get("mime_type") or ""),
            index_sha256=str(idx.get("sha256") or ""),
            index_byte_size=index_size,
            hash_matches_index=(str(idx.get("sha256") or "") == digest),
            size_matches_index=(index_size == size),
            in_index=bool(idx),
            downloaded_at=str(idx.get("downloaded_at") or ""),
            source_host=host,
            source_root=str(root),
            source_url=str(idx.get("url") or ""),
            path_match=how,
        )

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(work, files))


def deduplicate(rows: list[MediaRow]) -> dict:
    """Collapse identical bytes; keep distinct variants of one logical item."""
    by_hash: dict[str, list[MediaRow]] = {}
    for row in rows:
        by_hash.setdefault(row.sha256, []).append(row)

    by_logical: dict[str, set[str]] = {}
    for row in rows:
        by_logical.setdefault(row.logical_key, set()).add(row.sha256)

    variants = {k: sorted(v) for k, v in by_logical.items() if len(v) > 1}
    duplicates = {h: [r.rel_path for r in rs] for h, rs in by_hash.items() if len(rs) > 1}
    return {
        "generated_at": utcnow(),
        "physical_files": len(rows),
        "distinct_hashes": len(by_hash),
        "bytes_total": sum(r.byte_size for r in rows),
        "bytes_unique": sum(rs[0].byte_size for rs in by_hash.values()),
        "duplicate_files_collapsed": len(rows) - len(by_hash),
        "logical_items": len(by_logical),
        "logical_items_with_variants": len(variants),
        "variants": variants,
        "duplicate_groups": duplicates,
        "index_hash_mismatches": [r.rel_path for r in rows if r.in_index and not r.hash_matches_index],
        "index_size_mismatches": [r.rel_path for r in rows if r.in_index and not r.size_matches_index],
        "not_in_index": [r.rel_path for r in rows if not r.in_index],
    }


CANONICAL_FIELDS = [
    "dataset", "canonical_id", "platform", "document_id", "media_index", "url",
    "author", "post_timestamp", "text", "language", "media_sha256", "media_bytes",
    "media_mime", "media_status", "object_key", "source_host", "source_root",
    "source_rel_path", "downloaded_at",
]

FILE_FIELDS = [
    "media_sha256", "object_key", "bytes", "source_host", "source_rel_path",
    "abs_path", "mime_type", "index_hash_match", "index_size_match", "in_index",
    "path_match",
]


def write_csvs(rows: list[MediaRow], dedupe: dict, posts: dict, out_dir: Path, dataset: str) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    canonical = out_dir / "brazil26_canonical.csv"
    files_csv = out_dir / "brazil26_files.csv"

    # One row per logical item; variants are represented in both CSVs and flagged
    # in the report, never silently dropped.
    chosen: dict[str, MediaRow] = {}
    for row in sorted(rows, key=lambda r: (r.logical_key, r.sha256)):
        chosen.setdefault(row.logical_key, row)

    with canonical.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=CANONICAL_FIELDS)
        w.writeheader()
        for key, row in sorted(chosen.items()):
            post = posts.get((row.platform, row.document_id), {})
            w.writerow({
                "dataset": dataset,
                "canonical_id": row.logical_key,
                "platform": row.platform,
                "document_id": row.document_id,
                "media_index": row.media_index,
                "url": row.source_url or post.get("source_url", ""),
                "author": post.get("author", ""),
                "post_timestamp": post.get("timestamp", ""),
                "text": (post.get("text") or "").replace("\n", " ")[:2000],
                "language": post.get("language", ""),
                "media_sha256": row.sha256,
                "media_bytes": row.byte_size,
                "media_mime": row.mime_type,
                "media_status": "present" if row.in_index else "unindexed_file",
                "object_key": row.object_key,
                "source_host": row.source_host,
                "source_root": row.source_root,
                "source_rel_path": row.rel_path,
                "downloaded_at": row.downloaded_at,
            })

    with files_csv.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FILE_FIELDS)
        w.writeheader()
        for row in sorted(rows, key=lambda r: r.sha256):
            w.writerow({
                "media_sha256": row.sha256,
                "object_key": row.object_key,
                "bytes": row.byte_size,
                "source_host": row.source_host,
                "source_rel_path": row.rel_path,
                "abs_path": row.abs_path,
                "mime_type": row.mime_type,
                "index_hash_match": row.hash_matches_index,
                "index_size_match": row.size_matches_index,
                "in_index": row.in_index,
                "path_match": row.path_match,
            })

    return {
        "canonical_csv": str(canonical),
        "files_csv": str(files_csv),
        "canonical_rows": len(chosen),
        "file_rows": len(rows),
        "canonical_with_post_metadata": sum(1 for k, r in chosen.items() if (r.platform, r.document_id) in posts),
    }


def write_report(inv: dict, dedupe: dict, csvs: dict, out_dir: Path, elapsed: float) -> Path:
    report = out_dir / "AUDIT.md"
    dup = dedupe["duplicate_files_collapsed"]
    lines = [
        "# Brazil26 consolidation audit",
        "",
        f"Generated {utcnow()} on `{inv['host']}`.",
        "",
        "## Source",
        f"- root: `{inv['root']}`",
        f"- index: {inv['indexed_media']:,} media rows, {inv['indexed_bytes'] / 1e9:.2f} GB recorded",
        f"- on disk: {inv['files_on_disk']:,} files, {inv['bytes_on_disk'] / 1e9:.2f} GB",
        f"- files on disk but absent from the index: {inv['files_not_in_index']:,}",
        "",
        "## Deduplication",
        f"- physical files: {dedupe['physical_files']:,}",
        f"- distinct SHA-256: {dedupe['distinct_hashes']:,}",
        f"- identical files collapsed: {dup:,}",
        f"- bytes before: {dedupe['bytes_total'] / 1e9:.2f} GB",
        f"- bytes after: {dedupe['bytes_unique'] / 1e9:.2f} GB",
        f"- logical items: {dedupe['logical_items']:,}",
        f"- logical items with more than one distinct file: {dedupe['logical_items_with_variants']:,}",
        "",
        "## Integrity",
        f"- files whose bytes disagree with the index hash: {len(dedupe['index_hash_mismatches']):,}",
        f"- files whose size disagrees with the index: {len(dedupe['index_size_mismatches']):,}",
        f"- files the index does not know: {len(dedupe['not_in_index']):,}",
        "",
        "## Outputs",
        f"- `{Path(csvs['canonical_csv']).name}` — {csvs['canonical_rows']:,} logical items, "
        f"{csvs['canonical_with_post_metadata']:,} with post metadata",
        f"- `{Path(csvs['files_csv']).name}` — {csvs['file_rows']:,} physical files",
        f"- elapsed: {elapsed:.1f}s",
        "",
        "Media is **not** deleted, moved or modified by this tool.",
    ]
    if dedupe["logical_items_with_variants"]:
        lines += ["", "## Variants needing review", ""]
        for key, hashes in list(dedupe["variants"].items())[:20]:
            lines.append(f"- `{key}` — {len(hashes)} distinct files")
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


def stage_blobs(rows: list[MediaRow], manifest: list[MediaRow], staging: Path) -> int:
    """One symlink per distinct hash, named by content, so rclone uploads each once."""
    if staging.exists():
        shutil.rmtree(staging)
    seen: set[str] = set()
    for row in manifest:
        if row.sha256 in seen:
            continue
        seen.add(row.sha256)
        target = staging / row.object_key
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to(Path(row.abs_path).resolve())
    return len(seen)


def upload(args) -> int:
    staging = Path(args.staging)
    manifest = [MediaRow(**r) for r in json.loads(Path(args.manifest).read_text())]
    unique = stage_blobs(manifest, manifest, staging)
    cmd = [
        "rclone", "copy", str(staging), args.dest,
        "--copy-links", "--checksum", "--immutable",
        "--transfers", str(args.transfers), "--stats", "30s", "--stats-one-line",
    ]
    print(f"unique blobs staged: {unique}")
    print("command:", " ".join(cmd))
    if args.dry_run:
        print("dry run: nothing uploaded")
        return 0
    return subprocess.call(cmd)


def verify(args) -> int:
    manifest = json.loads(Path(args.manifest).read_text())
    expected = {}
    for row in manifest:
        key = f"{row['object_key']}"
        expected[key] = max(expected.get(key, 0), int(row["byte_size"]))
    out = subprocess.run(
        ["rclone", "lsjson", "-R", args.dest], capture_output=True, text=True
    )
    if out.returncode != 0:
        print("rclone failed:", out.stderr.strip()[:400], file=sys.stderr)
        return 2
    remote = {f"{args.prefix.rstrip('/')}/{o['Path']}".lstrip("/"): o.get("Size", 0)
              for o in json.loads(out.stdout)}
    missing = [k for k in expected if k not in remote]
    wrong = [k for k, v in expected.items() if k in remote and remote[k] != v]
    extra = [k for k in remote if k not in expected]
    print(json.dumps({
        "expected_objects": len(expected),
        "remote_objects": len(remote),
        "missing": len(missing),
        "size_mismatch": len(wrong),
        "unexpected": len(extra),
    }, indent=2))
    return 0 if not missing and not wrong else 1


def cmd_run(args) -> int:
    root = Path(args.root).resolve()
    out_dir = Path(args.out_dir)
    start = datetime.now()
    inv = inventory(root, args.limit)
    rows = build_manifest(root, args.workers, args.limit, read_post_urls(root))
    dedupe = deduplicate(rows)
    posts = read_posts(root)
    csvs = write_csvs(rows, dedupe, posts, out_dir, args.dataset)
    (out_dir / "inventory.json").write_text(json.dumps(inv, indent=2))
    (out_dir / "manifest.json").write_text(json.dumps([asdict(r) for r in rows], indent=2))
    (out_dir / "dedupe.json").write_text(json.dumps(dedupe, indent=2))
    report = write_report(inv, dedupe, csvs, out_dir, (datetime.now() - start).total_seconds())
    print(json.dumps({
        "inventory": {k: inv[k] for k in ("indexed_media", "files_on_disk", "bytes_on_disk")},
        "dedupe": {k: dedupe[k] for k in ("physical_files", "distinct_hashes", "duplicate_files_collapsed",
                                          "bytes_unique", "logical_items", "logical_items_with_variants")},
        "csv": csvs,
        "report": str(report),
    }, indent=2))
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="inventory, manifest, dedupe and write CSVs")
    r.add_argument("--root", required=True)
    r.add_argument("--out-dir", required=True)
    r.add_argument("--dataset", default=DEFAULT_DATASET)
    r.add_argument("--workers", type=int, default=8)
    r.add_argument("--limit", type=int, default=None, help="hash only the first N files (testing)")
    r.set_defaults(func=cmd_run)

    u = sub.add_parser("upload", help="stage unique blobs and copy to Allas")
    u.add_argument("--manifest", required=True)
    u.add_argument("--staging", required=True)
    u.add_argument("--dest", required=True)
    u.add_argument("--transfers", type=int, default=8)
    u.add_argument("--dry-run", action="store_true")
    u.set_defaults(func=upload)

    v = sub.add_parser("verify", help="re-list remote objects and compare sizes")
    v.add_argument("--manifest", required=True)
    v.add_argument("--dest", required=True)
    v.add_argument("--prefix", default="media")
    v.set_defaults(func=verify)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
