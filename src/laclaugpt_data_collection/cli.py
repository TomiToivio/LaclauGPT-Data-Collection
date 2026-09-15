"""Command-line entry point for public-safe collection utilities."""
from __future__ import annotations

import argparse
import json
import os
import sys
import tomllib
from pathlib import Path

from .config import Settings
from .deployment import render_cron, render_systemd_units, validate_profile


def _apply_profile(path: Path) -> None:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    storage = data.get("storage", {})
    paths = data.get("paths", {})
    browser_capture = data.get("browser_capture", {})
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
    server.add_argument("--study-config", required=True,
                        help="study YAML configuration (ignored local file)")
    server.add_argument("--data-root", required=True,
                        help="persistent collection data root")
    server.add_argument("--host", default="127.0.0.1")
    server.add_argument("--port", type=int, default=8765)
    server.set_defaults(func=_capture_server)
    return parser


def _capture_server(args: argparse.Namespace) -> int:
    from .capture_server import main as server_main

    return server_main([
        "--study-config", args.study_config,
        "--data-root", args.data_root,
        "--host", args.host,
        "--port", str(args.port),
    ])


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
