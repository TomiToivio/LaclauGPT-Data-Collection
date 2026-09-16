"""Inspect layered Collection configuration without exposing private targets/secrets."""
from __future__ import annotations

import argparse
import json
from typing import Any

from .effective_config import resolve_collection_config


def _json_mapping(value: str) -> dict[str, Any]:
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise argparse.ArgumentTypeError("--override-json must contain a JSON object")
    return {str(key): item for key, item in parsed.items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="laclaugpt-config")
    parser.add_argument("--project", required=True, help="project/study YAML or TOML layer")
    parser.add_argument("--arena", help="optional arena YAML or TOML layer")
    parser.add_argument("--machine", help="optional machine/deployment YAML or TOML layer")
    parser.add_argument("--execution", help="optional execution YAML or TOML layer")
    parser.add_argument(
        "--private-override",
        action="append",
        default=[],
        help="private runtime override layer; may be repeated",
    )
    parser.add_argument(
        "--override-json",
        type=_json_mapping,
        help="final explicit override as a JSON object",
    )
    args = parser.parse_args(argv)
    effective = resolve_collection_config(
        project=args.project,
        arena=args.arena,
        machine=args.machine,
        execution=args.execution,
        private_overrides=args.private_override,
        overrides=args.override_json,
    )
    print(json.dumps(effective.safe_snapshot(), indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
