"""Command-line entry point for public-safe collection utilities."""
from __future__ import annotations

import argparse
import json
import os
import sys
import tomllib
from dataclasses import asdict
from pathlib import Path

from .config import Settings
from .deployment import render_cron, render_systemd_units, validate_profile


def _apply_profile(path: Path) -> None:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    storage = data.get("storage", {})
    paths = data.get("paths", {})
    browser_capture = data.get("browser_capture", {})
    collector = data.get("collector", {})
    mapping = {
        "LACLAUGPT_PROFILE": data.get("profile"),
        "LACLAUGPT_MACHINE": data.get("machine"),
        "LACLAUGPT_EXECUTION": data.get("execution"),
        "LACLAUGPT_BROWSER": data.get("browser"),
        "LACLAUGPT_RECORD_BACKEND": storage.get("records"),
        "LACLAUGPT_OBJECT_BACKEND": storage.get("objects"),
        "LACLAUGPT_CACHE_BACKEND": storage.get("cache"),
        "LACLAUGPT_DATA_ROOT": paths.get("data_root"),
        "LACLAUGPT_SQLITE_PATH": paths.get("sqlite_path"),
        "LACLAUGPT_BROWSER_HOST": browser_capture.get("host"),
        "LACLAUGPT_BROWSER_PORT": browser_capture.get("port"),
        "LACLAUGPT_CAPTURE_MEDIA_INLINE": collector.get("download_media"),
        "LACLAUGPT_CAPTURE_MEDIA_MAX_BYTES": collector.get("media_max_bytes"),
    }
    for key, value in mapping.items():
        if value is not None and key not in os.environ:
            os.environ[key] = str(value)


def _doctor(args: argparse.Namespace) -> int:
    if args.profile:
        _apply_profile(Path(args.profile))
    settings = Settings()
    settings.ensure_local_directories()
    summary = settings.safe_summary()
    problems = validate_profile(settings)
    summary["python"] = sys.version.split()[0]
    summary["status"] = "ok" if not problems else "invalid"
    summary["problems"] = problems
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if not problems else 2


def _plugins_list(_args: argparse.Namespace) -> int:
    from .plugins import default_registry

    plugins = [asdict(spec) for spec in default_registry().specs()]
    print(json.dumps(plugins, indent=2, sort_keys=True))
    return 0


def _manifest_drift(args: argparse.Namespace) -> int:
    from .manifest_drift import compare_manifests, drift_summary

    report = compare_manifests(args.deployed, args.tracked)
    print(json.dumps(report, indent=2, sort_keys=True))
    print(drift_summary(report), file=sys.stderr)
    if args.fail_on_drift and not report["in_sync"]:
        return 1
    return 0


def _corpus_audit(args: argparse.Namespace) -> int:
    """Read-only coverage/concentration report over a record source."""
    import json as _json
    from pathlib import Path as _Path

    from .corpus_audit import audit_records, audit_summary

    records: list[dict] = []
    if args.records:
        path = _Path(args.records)
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                records.append(_json.loads(line))
    elif args.mongodb_uri:
        # Import inside the branch so the base install needs no pymongo.
        from pymongo import MongoClient

        client = MongoClient(args.mongodb_uri, serverSelectionTimeoutMS=5000)
        collection = client[args.mongodb_database][args.mongodb_collection]
        query = {"project_id": args.project} if args.project else {}
        records = list(collection.find(query, {"_id": 0}).limit(args.limit))
    else:
        print(json.dumps({"status": "error", "error": "pass --records or --mongodb-uri"}))
        return 2

    configured: list[str] = []
    if args.configured_sources:
        configured = [
            line.strip()
            for line in _Path(args.configured_sources).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    deferred: list[str] = []
    if args.study_config:
        import yaml as _yaml

        study = _yaml.safe_load(_Path(args.study_config).read_text(encoding="utf-8")) or {}
        for stage in (study.get("stage_reachability") or {}).values():
            if isinstance(stage, dict):
                deferred.extend(
                    str(p) for p in (stage.get("deferred") or []) if isinstance(p, str)
                )
    report = audit_records(
        records,
        top_n=args.top_n,
        publication_floor=args.publication_floor or "",
        configured_sources=configured,
        deferred_platforms=deferred,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    print(audit_summary(report), file=sys.stderr)
    return 0


def _distributed_check(args: argparse.Namespace) -> int:
    from .distributed_capture import DistributedCaptureSink

    settings = Settings()
    problems = validate_profile(settings)
    if problems:
        print(json.dumps({"status": "invalid", "problems": problems}, indent=2))
        return 2
    sink = DistributedCaptureSink(settings)
    sink.assert_private_config(args.study_config)
    print(json.dumps({"status": "ok", **sink.smoke_check()}, indent=2, sort_keys=True))
    return 0


def _distributed_sync(args: argparse.Namespace) -> int:
    from .distributed_sync import sync_normalized_records

    settings = Settings()
    problems = validate_profile(settings)
    if problems:
        print(json.dumps({"status": "invalid", "problems": problems}, indent=2))
        return 2
    result = sync_normalized_records(
        settings,
        study_config=args.study_config,
        data_root=Path(args.data_root),
        limit=args.limit,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def _schedule(args: argparse.Namespace) -> int:
    command = args.command_line
    if args.kind == "cron":
        print(render_cron(command, schedule=args.schedule))
    else:
        units = render_systemd_units(command, working_directory=Path(args.working_directory))
        print("# laclaugpt-collection.service")
        print(units["service"])
        print("# laclaugpt-collection.timer")
        print(units["timer"])
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="laclaugpt-collect")
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="validate a safe local/server profile")
    doctor.add_argument("--profile", help="path to a checked-in example or ignored local TOML profile")
    doctor.set_defaults(func=_doctor)

    drift = sub.add_parser(
        "manifest-drift",
        help="report how the deployed source manifest differs from the tracked plan",
    )
    drift.add_argument("--deployed", required=True, help="manifest the pipeline reads")
    drift.add_argument("--tracked", required=True, help="audited plan under configs/studies/")
    drift.add_argument(
        "--fail-on-drift",
        action="store_true",
        help="exit 1 when the manifests differ (for a CI or cron gate)",
    )
    drift.set_defaults(func=_manifest_drift)

    audit = sub.add_parser(
        "corpus-audit",
        help="read-only coverage and concentration report for the store",
    )
    audit.add_argument("--records", help="JSONL of canonical records (offline)")
    audit.add_argument("--mongodb-uri", help="Mongo URI to read from (read-only)")
    audit.add_argument("--mongodb-database", default="spectacleScraper")
    audit.add_argument("--mongodb-collection", default="ai26__records")
    audit.add_argument("--project", default="", help="project_id filter")
    audit.add_argument("--limit", type=int, default=5000)
    audit.add_argument("--top-n", type=int, default=3, help="dominance window")
    audit.add_argument("--publication-floor", default="", help="ISO date, e.g. 2026-09-01")
    audit.add_argument(
        "--configured-sources",
        help="file of source names/handles the manifest declares (one per line)",
    )
    audit.add_argument(
        "--study-config",
        help="study YAML; reads its stage_reachability block so stage-deferred "
             "platforms are not reported as unexplained coverage gaps (#207)",
    )
    audit.set_defaults(func=_corpus_audit)

    plugins = sub.add_parser("plugins", help="inspect the versioned collection-plugin registry")
    plugin_sub = plugins.add_subparsers(dest="plugins_command", required=True)
    plugin_list = plugin_sub.add_parser("list", help="list built-in plugin declarations")
    plugin_list.set_defaults(func=_plugins_list)

    check = sub.add_parser(
        "distributed-check",
        help="validate distributed AI26-style backends without exposing secrets",
    )
    check.add_argument(
        "--study-config",
        required=True,
        help="private study YAML below LACLAUGPT_PRIVATE_CONFIG_DIR",
    )
    check.set_defaults(func=_distributed_check)

    sync = sub.add_parser(
        "distributed-sync",
        help="mirror locally captured canonical JSONL records to MongoDB/S3/Redis",
    )
    sync.add_argument(
        "--study-config",
        required=True,
        help="private study YAML below LACLAUGPT_PRIVATE_CONFIG_DIR",
    )
    sync.add_argument("--data-root", required=True, help="Firefox capture data root")
    sync.add_argument(
        "--limit",
        type=int,
        default=25,
        help="bounded number of records per invocation (default: 25)",
    )
    sync.set_defaults(func=_distributed_sync)

    schedule = sub.add_parser("schedule", help="render cron/systemd examples without installing them")
    schedule.add_argument("kind", choices=("cron", "systemd"))
    schedule.add_argument("--command-line", default="laclaugpt-collect doctor")
    schedule.add_argument("--schedule", default="17 * * * *")
    schedule.add_argument("--working-directory", default="/opt/laclaugpt-collection")
    schedule.set_defaults(func=_schedule)

    server = sub.add_parser(
        "capture-server",
        help="run the local HTTP capture backend for the browser extension",
    )
    server.add_argument(
        "--study-config",
        required=True,
        help="study YAML configuration (ignored local file)",
    )
    server.add_argument("--data-root", required=True, help="persistent collection data root")
    server.add_argument("--host", default="127.0.0.1")
    server.add_argument("--port", type=int, default=8765)
    server.set_defaults(func=_capture_server)
    return parser


def _capture_server(args: argparse.Namespace) -> int:
    from .capture_server import main as server_main

    return server_main(
        [
            "--study-config",
            args.study_config,
            "--data-root",
            args.data_root,
            "--host",
            args.host,
            "--port",
            str(args.port),
        ]
    )


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
