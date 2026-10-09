#!/usr/bin/env python3
"""Review and explicitly deploy the audited AI26 source manifest to local runtime data.

Dry-run by default. Never touches credentials, the study YAML or database records.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path


KINDS = ("feed", "web_source", "x_account", "bluesky_account", "mastodon_account", "arxiv_query")


def identities(document: dict) -> set[tuple[str, str]]:
    """Use kind-scoped source identities; inactive rows do not run."""
    found: set[tuple[str, str]] = set()
    for kind in KINDS:
        for row in document.get(kind, []):
            if not isinstance(row, dict) or row.get("active", row.get("enabled", True)) is False:
                continue
            key = next((str(row[field]).strip().rstrip("/") for field in
                        ("feed_url", "url", "handle", "query", "name")
                        if row.get(field)), "")
            if key:
                found.add((kind, key))
    return found


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tracked", type=Path, default=Path("configs/studies/ai26.sources.example.toml"))
    parser.add_argument("--deployed", type=Path, default=Path("data/config/ai26.sources.toml"))
    parser.add_argument("--apply", action="store_true", help="Copy after review, creating a timestamped backup")
    parser.add_argument("--allow-removals", action="store_true",
                        help="Explicitly acknowledge dropping deployed active source identities")
    args = parser.parse_args(argv)

    if args.tracked.is_symlink() or args.deployed.is_symlink():
        parser.error("symlink manifests are not allowed")
    if not args.tracked.is_file():
        parser.error(f"tracked manifest missing: {args.tracked}")
    if args.deployed.exists() and not args.deployed.is_file():
        parser.error(f"deployed path is not a regular file: {args.deployed}")
    tracked_bytes = args.tracked.read_bytes()
    existing_bytes = args.deployed.read_bytes() if args.deployed.exists() else b""
    tracked = tomllib.loads(tracked_bytes.decode("utf-8"))
    deployed = tomllib.loads(existing_bytes.decode("utf-8")) if existing_bytes else {}
    old_sources, new_sources = identities(deployed), identities(tracked)
    additions = sorted(new_sources - old_sources)
    removals = sorted(old_sources - new_sources)
    print(f"tracked sha256:  {digest(tracked_bytes)}")
    print(f"deployed sha256: {digest(existing_bytes) if existing_bytes else '(missing)'}")
    print(f"added active sources: {len(additions)}; removed active sources: {len(removals)}")
    for kind, value in additions:
        print(f"+ {kind}: {value}")
    for kind, value in removals:
        print(f"- {kind}: {value}")
    if tracked_bytes == existing_bytes:
        print("Already synchronized; no change.")
        return 0

    diff = difflib.unified_diff(existing_bytes.decode("utf-8").splitlines(),
                                tracked_bytes.decode("utf-8").splitlines(),
                                fromfile=str(args.deployed), tofile=str(args.tracked),
                                lineterm="")
    print("\n".join(diff))
    if not args.apply:
        print("DRY RUN ONLY. Re-run with --apply to deploy; --allow-removals if needed.")
        return 0
    if removals and not args.allow_removals:
        print("REFUSED: existing active sources would be removed; review and pass --allow-removals.", file=sys.stderr)
        return 2
    args.deployed.parent.mkdir(parents=True, exist_ok=True)
    if existing_bytes:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup = args.deployed.with_name(f"{args.deployed.name}.backup-{stamp}")
        with backup.open("xb") as destination:
            destination.write(existing_bytes)
        print(f"Backed up previous manifest: {backup}")
    temporary = args.deployed.with_name(f".{args.deployed.name}.tmp")
    if temporary.exists():
        print(f"REFUSED: temporary path already exists: {temporary}", file=sys.stderr)
        return 2
    try:
        with temporary.open("xb") as destination:
            destination.write(tracked_bytes)
        temporary.replace(args.deployed)
    finally:
        temporary.unlink(missing_ok=True)
    print(f"Deployed tracked manifest: {args.deployed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
