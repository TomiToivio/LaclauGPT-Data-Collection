"""Import/export validated Collection configuration through Redis."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .config import Settings
from .effective_config import resolve_collection_config
from .redis_control import RedisProjectConfig, redis_client


def _json_mapping(value: str) -> dict[str, Any]:
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise argparse.ArgumentTypeError("--override-json must contain a JSON object")
    return {str(key): item for key, item in parsed.items()}


def _store(settings: Settings) -> RedisProjectConfig:
    if settings.distributed_config_backend != "redis":
        raise SystemExit(
            "distributed config is not enabled; set LACLAUGPT_DISTRIBUTED_CONFIG_BACKEND=redis"
        )
    client = redis_client(settings.redis_url)
    return RedisProjectConfig(
        client,
        settings.distributed_namespace,
        snapshot_root=settings.redis_config_snapshot_root,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="laclaugpt-redis-config")
    sub = parser.add_subparsers(dest="command", required=True)

    push = sub.add_parser("push", help="resolve local layers, validate, then publish a revision")
    push.add_argument("--project", required=True, help="project/study YAML or TOML layer")
    push.add_argument("--arena")
    push.add_argument("--machine")
    push.add_argument("--execution")
    push.add_argument("--private-override", action="append", default=[])
    push.add_argument("--override-json", type=_json_mapping)
    push.add_argument("--actor", default="human-cli")
    push.add_argument("--source", default="cli")

    pull = sub.add_parser("pull", help="export current/selected Redis config revision to JSON")
    pull.add_argument("--revision", default="current")
    pull.add_argument("--output", required=True, type=Path)

    show = sub.add_parser("show", help="print Redis config metadata and config as JSON")
    show.add_argument("--revision", default="current")

    args = parser.parse_args(argv)
    settings = Settings()
    store = _store(settings)

    if args.command == "push":
        effective = resolve_collection_config(
            project=args.project,
            arena=args.arena,
            machine=args.machine,
            execution=args.execution,
            private_overrides=args.private_override,
            overrides=args.override_json,
        )
        item = store.publish(effective, actor=args.actor, source=args.source)
        print(json.dumps(item.as_dict(), indent=2, sort_keys=True, default=str))
        return 0

    if args.command == "pull":
        item = store.export(args.output, args.revision)
        print(f"exported {item.project_id} collection config {item.revision} to {args.output}")
        return 0

    item = store.load(args.revision)
    print(json.dumps(item.as_dict(), indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
