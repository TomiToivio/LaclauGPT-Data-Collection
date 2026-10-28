"""Offline Brazil26 multi-machine inventory and conflict-preserving reconciliation.

No credentials, network access, deletion, or upload operations. Source-specific metadata
is supplied by CSV rows whose media_path references a file relative to the CSV directory.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

FIELDS = [
    "dataset", "platform", "post_id", "canonical_id", "source_url", "creator",
    "post_timestamp", "collection_timestamp", "download_timestamp", "caption",
    "media_sha256", "media_size", "media_status", "allas_object_key",
    "source_hosts", "source_metadata_ids", "variant_count", "conflict_fields",
]
MEDIA_FIELDS = [
    "canonical_id", "sha256", "size", "object_key", "source_host", "source_path",
    "source_metadata_id", "status",
]
PROVENANCE_FIELDS = ["canonical_id", "source_host", "source_metadata_id", "source_csv", "source_row", "raw_json"]


def file_hash(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def normal_url(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    bits = urlsplit(value)
    return urlunsplit((bits.scheme.lower(), bits.netloc.lower(), bits.path.rstrip("/"), "", ""))


def normal_platform(value: str) -> str:
    alias = {"twitter": "x", "twitter.com": "x", "x.com": "x", "ig": "instagram", "tt": "tiktok"}
    name = value.strip().lower()
    return alias.get(name, name)


def record_id(row: dict[str, str]) -> str:
    platform = normal_platform(row.get("platform", ""))
    post_id = (row.get("post_id") or row.get("video_id") or "").strip()
    if not platform or not post_id:
        raise ValueError("platform and post_id/video_id are mandatory; no identity guessed from filename")
    return f"{platform}:{post_id}"


def inventory(sources: list[tuple[str, Path]], output: Path) -> dict:
    """Produce deterministic manifests from explicit host -> metadata CSV mappings."""
    output.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    missing: list[dict] = []
    for host, csv_path in sorted(sources):
        with csv_path.open(encoding="utf-8-sig", newline="") as handle:
            for index, raw in enumerate(csv.DictReader(handle), 2):
                row = {str(k): str(v or "") for k, v in raw.items() if k is not None}
                try:
                    ident = record_id(row)
                except ValueError as exc:
                    missing.append({"host": host, "csv": str(csv_path), "row": index, "error": str(exc)})
                    continue
                media = row.get("media_path", "").strip()
                sha = ""
                size = ""
                status = "missing_media"
                resolved = ""
                if media:
                    candidate = (csv_path.parent / media).resolve()
                    # Never allow arbitrary absolute paths or traversal from a manifest.
                    if candidate.is_relative_to(csv_path.parent.resolve()) and candidate.is_file():
                        sha, length = file_hash(candidate)
                        size = str(length)
                        resolved = str(candidate)
                        status = "local"
                rows.append({
                    "id": ident, "host": host, "source_csv": str(csv_path),
                    "source_row": index, "source_path": resolved,
                    "sha": sha, "size": size, "status": status, "raw": row,
                })
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[row["id"]].append(row)
    canonical: list[dict] = []
    media_rows: list[dict] = []
    provenance: list[dict] = []
    conflicts: list[dict] = []
    object_hashes: set[str] = set()
    for ident in sorted(grouped):
        group = sorted(grouped[ident], key=lambda r: (r["host"], r["source_csv"], r["source_row"]))
        values: dict[str, str] = {}
        conflict_fields: list[str] = []
        fields = ["source_url", "creator", "post_timestamp", "collection_timestamp",
                  "download_timestamp", "caption"]
        for field in fields:
            variants = sorted({normal_url(r["raw"].get(field, "")) if field == "source_url"
                               else r["raw"].get(field, "").strip()
                               for r in group if r["raw"].get(field, "").strip()})
            values[field] = variants[0] if variants else ""
            if len(variants) > 1:
                conflict_fields.append(field)
                conflicts.append({"canonical_id": ident, "field": field, "values": variants})
        variants_by_hash: dict[str, list[dict]] = defaultdict(list)
        for row in group:
            if row["sha"]:
                variants_by_hash[row["sha"]].append(row)
            provenance.append({
                "canonical_id": ident, "source_host": row["host"],
                "source_metadata_id": row["raw"].get("metadata_id", ""),
                "source_csv": row["source_csv"], "source_row": row["source_row"],
                "raw_json": json.dumps(row["raw"], sort_keys=True, ensure_ascii=False),
            })
            if not row["sha"]:
                missing.append({"host": row["host"], "csv": row["source_csv"],
                                "row": row["source_row"], "canonical_id": ident,
                                "error": "media not found or path outside CSV directory"})
        for sha, occurrences in sorted(variants_by_hash.items()):
            object_hashes.add(sha)
            primary = occurrences[0]
            media_rows.append({
                "canonical_id": ident, "sha256": sha, "size": primary["size"],
                "object_key": f"brazil26/videos/sha256/{sha[:2]}/{sha}",
                "source_host": ";".join(sorted({o["host"] for o in occurrences})),
                "source_path": primary["source_path"],
                "source_metadata_id": ";".join(sorted({o["raw"].get("metadata_id", "") for o in occurrences})),
                "status": "pending_upload",
            })
        canonical.append({
            "dataset": "Brazil26", "platform": ident.split(":", 1)[0],
            "post_id": ident.split(":", 1)[1], "canonical_id": ident,
            **values, "media_sha256": sorted(variants_by_hash)[0] if variants_by_hash else "",
            "media_size": variants_by_hash[sorted(variants_by_hash)[0]][0]["size"] if variants_by_hash else "",
            "media_status": "pending_upload" if variants_by_hash else "missing_media",
            "allas_object_key": f"brazil26/videos/sha256/{sorted(variants_by_hash)[0][:2]}/{sorted(variants_by_hash)[0]}" if variants_by_hash else "",
            "source_hosts": ";".join(sorted({o["host"] for o in group})),
            "source_metadata_ids": ";".join(sorted({o["raw"].get("metadata_id", "") for o in group})),
            "variant_count": len(variants_by_hash),
            "conflict_fields": ";".join(conflict_fields),
        })
    def write_csv(path: Path, fields: list[str], entries: list[dict]) -> None:
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(entries)
    write_csv(output / "canonical_metadata.csv", FIELDS, canonical)
    write_csv(output / "media_manifest.csv", MEDIA_FIELDS, media_rows)
    write_csv(output / "source_provenance.csv", PROVENANCE_FIELDS, provenance)
    (output / "conflicts.json").write_text(json.dumps(conflicts, indent=2, ensure_ascii=False), encoding="utf-8")
    (output / "exceptions.json").write_text(json.dumps(missing, indent=2, ensure_ascii=False), encoding="utf-8")
    summary = {
        "status": "offline_only_not_uploaded", "sources": len(sources), "records": len(rows),
        "logical_videos": len(canonical), "media_variants": len(media_rows),
        "unique_file_hashes": len(object_hashes), "duplicate_media_references": sum(
            1 for r in rows if r["sha"]) - len(object_hashes),
        "conflicts": len(conflicts), "exceptions": len(missing),
        "upload_verified": False, "allas_checked": False,
    }
    (output / "report.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", action="append", required=True,
                        help="HOST=/path/to/metadata.csv (repeat for each machine)")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    sources = []
    for source in args.source:
        host, sep, path = source.partition("=")
        if not sep or not host or not path:
            parser.error("--source must be HOST=/path/to/metadata.csv")
        sources.append((host, Path(path).resolve()))
    print(json.dumps(inventory(sources, args.output), indent=2))


if __name__ == "__main__":
    main()
