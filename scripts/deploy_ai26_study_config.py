#!/usr/bin/env python3
"""Review and explicitly deploy the audited AI26 study YAML to local runtime data.

Dry-run by default. Never touches credentials, the source manifest or database
records.

Issue #239 item 4: the deployed study YAML at `data/config/ai26.yaml` had drifted
from the audited plan -- a `paper:` pointer at a file that does not exist on main,
no `stage_reachability` block, and 8 of 11 groups. `docs/AI26_SOURCE_DEPLOYMENT.md`
documents the *source manifest* deploy path; there was no equivalent for the study
YAML, so the drift had no repair. This closes that gap with the same guard
discipline as `deploy_ai26_sources.py`.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def validate_study_bytes(content: bytes, *, source: str) -> list[str]:
    """Return the reasons a study YAML must not be deployed. Empty means valid.

    The study YAML drives collection policy, so a malformed or unsafe file must be
    refused *before* it reaches the running pipeline, not discovered by a cycle.
    """
    import yaml

    problems: list[str] = []
    try:
        data = yaml.safe_load(content.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        return [f"{source}: not valid YAML: {exc}"]
    if not isinstance(data, dict):
        return [f"{source}: study config must be a mapping"]
    if not data.get("study"):
        problems.append(f"{source}: missing 'study'")
    paper = data.get("paper")
    if isinstance(paper, str) and paper:
        # The deployed file previously pointed at paper/PAPER.md, which does not
        # exist on main. A study must not reference a paper path that is absent.
        name = paper.rstrip("/").split("/")[-1]
        if not name.endswith(".md"):
            problems.append(f"{source}: paper must point at a markdown file, got {paper!r}")
    # Credential detection must look at KEYS, not free text: a study config
    # legitimately mentions "secrets" in prose ("machine-specific secrets stay
    # outside Git"), and a substring scan would refuse a valid file. Only a key
    # that would actually carry a secret is a problem.
    credential_keys = {"password", "passwd", "secret", "token", "api_key", "apikey", "private_key"}
    for path, key in _walk_keys(data):
        if key.casefold() in credential_keys:
            problems.append(f"{source}: credential-like key at {path}: {key!r}")
    return problems


def _walk_keys(node: object, prefix: str = "$") -> list[tuple[str, str]]:
    """Every (path, key) pair in a parsed config, so checks can be structural."""
    found: list[tuple[str, str]] = []
    if isinstance(node, dict):
        for key, value in node.items():
            found.append((f"{prefix}.{key}", str(key)))
            found.extend(_walk_keys(value, f"{prefix}.{key}"))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            found.extend(_walk_keys(value, f"{prefix}[{index}]"))
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tracked",
        type=Path,
        default=Path("configs/studies/ai26.example.yaml"),
        help="the audited study YAML in Git",
    )
    parser.add_argument(
        "--deployed",
        type=Path,
        default=Path("data/config/ai26.yaml"),
        help="the runtime study YAML the pipeline reads",
    )
    parser.add_argument("--apply", action="store_true", help="Copy after review, creating a timestamped backup")
    args = parser.parse_args(argv)

    if args.tracked.is_symlink() or args.deployed.is_symlink():
        parser.error("symlink study configs are not allowed")
    if not args.tracked.is_file():
        parser.error(f"tracked study config missing: {args.tracked}")
    if args.deployed.exists() and not args.deployed.is_file():
        parser.error(f"deployed path is not a regular file: {args.deployed}")

    tracked_bytes = args.tracked.read_bytes()
    existing_bytes = args.deployed.read_bytes() if args.deployed.exists() else b""

    problems = validate_study_bytes(tracked_bytes, source=str(args.tracked))
    if problems:
        for problem in problems:
            print(f"REFUSED: {problem}", file=sys.stderr)
        return 2

    print(f"tracked sha256:  {digest(tracked_bytes)}")
    print(f"deployed sha256: {digest(existing_bytes) if existing_bytes else '(missing)'}")
    if tracked_bytes == existing_bytes:
        print("Already synchronized; no change.")
        return 0

    diff = difflib.unified_diff(
        existing_bytes.decode("utf-8", errors="replace").splitlines(),
        tracked_bytes.decode("utf-8").splitlines(),
        fromfile=str(args.deployed),
        tofile=str(args.tracked),
        lineterm="",
    )
    print("\n".join(diff))
    if not args.apply:
        print("DRY RUN ONLY. Re-run with --apply to deploy.")
        return 0

    args.deployed.parent.mkdir(parents=True, exist_ok=True)
    if existing_bytes:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup = args.deployed.with_name(f"{args.deployed.name}.backup-{stamp}")
        with backup.open("xb") as destination:
            destination.write(existing_bytes)
        print(f"Backed up previous study config: {backup}")
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
    print(f"Deployed tracked study config: {args.deployed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
