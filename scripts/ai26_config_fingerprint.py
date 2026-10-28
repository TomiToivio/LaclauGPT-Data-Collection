#!/usr/bin/env python3
"""Compare AI26 effective study/source config fingerprints without exposing values.

Run independently on each host and exchange only JSON reports, never private configs.
The effective representation is parsed TOML/YAML, not byte-for-byte formatting.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tomllib
from pathlib import Path

import yaml

FIELDS = ("sources_sha256", "study_sha256")
FORMAT = "ai26-config-fingerprint-v1"


def fingerprint(sources: Path, study: Path) -> dict[str, str]:
    with sources.open("rb") as stream:
        source_data = tomllib.load(stream)
    study_data = yaml.safe_load(study.read_text(encoding="utf-8"))
    if not isinstance(source_data, dict) or not isinstance(study_data, dict):
        raise ValueError("AI26 sources and study must contain mapping documents")

    def digest(value: object) -> str:
        canonical = json.dumps(value, sort_keys=True, separators=(",", ":"),
                               ensure_ascii=False, allow_nan=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    return {"format": FORMAT, "sources_sha256": digest(source_data),
            "study_sha256": digest(study_data)}


def compare(reports: list[dict[str, str]]) -> bool:
    return (len(reports) >= 2
            and all(r.get("format") == FORMAT and
                    all(isinstance(r.get(k), str) and len(r[k]) == 64 for k in FIELDS)
                    for r in reports)
            and all(all(r[k] == reports[0][k] for k in FIELDS) for r in reports[1:]))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", type=Path)
    parser.add_argument("--study", type=Path)
    parser.add_argument("--compare", nargs="+", type=Path, metavar="REPORT")
    args = parser.parse_args(argv)
    if args.compare:
        if args.sources or args.study:
            parser.error("--compare cannot be combined with --sources/--study")
        try:
            reports = [json.loads(p.read_text(encoding="utf-8")) for p in args.compare]
            matched = compare(reports)
        except (OSError, ValueError, TypeError) as exc:
            print(f"AI26_CONFIG_PARITY=error ({type(exc).__name__})", file=sys.stderr)
            return 2
        print("AI26_CONFIG_PARITY=" + ("match" if matched else "mismatch"))
        return 0 if matched else 1
    if not args.sources or not args.study:
        parser.error("--sources and --study are required without --compare")
    try:
        print(json.dumps(fingerprint(args.sources, args.study), sort_keys=True))
    except (OSError, ValueError, yaml.YAMLError, tomllib.TOMLDecodeError) as exc:
        print(f"AI26_CONFIG_FINGERPRINT=error ({type(exc).__name__})", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
