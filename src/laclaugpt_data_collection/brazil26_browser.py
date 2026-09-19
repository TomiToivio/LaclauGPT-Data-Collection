"""Brazil26 researcher-facing Firefox collection runtime.

The public CLI keeps the low-level backend/check/media subcommands for
automation, while invoking laclaugpt-brazil26 with no subcommand starts the
human-researcher session: resolve the private study config, ensure the
Brazil26 cron block, start the localhost capture backend, and launch Firefox.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

from .capture_server import CaptureServer
from .config import Settings
from .distributed_capture import DistributedCaptureSink
from .distributed_media_runner import MediaRunLockedError, run_distributed_media
from .store import utc_stamp
from .study import load_config

PROJECT_ID = "brazil26"
DEFAULT_PRIVATE_CONFIG = Path("collection/brazil26/brazil-election-2026.yaml")
_LOOPBACK = {"127.0.0.1", "localhost", "::1"}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _resolve_study_config(
    value: str | Path | None = None, *, repo_root: Path | None = None
) -> Path:
    """Resolve the real Brazil26 config without falling back to demo data."""
    if value:
        path = Path(value).expanduser()
    else:
        configured = (
            os.environ.get("BRAZIL26_CONFIG", "").strip()
            or os.environ.get("LACLAUGPT_STUDY_CONFIG", "").strip()
        )
        if configured:
            path = Path(configured).expanduser()
        else:
            root = repo_root or _repo_root()
            private_repo = Path(
                os.environ.get("LACLAUGPT_PRIVATE_REPO", root.parent / "LaclauGPT-Private")
            ).expanduser()
            path = private_repo / DEFAULT_PRIVATE_CONFIG
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(
            "Brazil26 private study config not found: "
            f"{path}. Expected LaclauGPT-Private/{DEFAULT_PRIVATE_CONFIG.as_posix()} "
            "or set BRAZIL26_CONFIG/LACLAUGPT_STUDY_CONFIG."
        )
    return path


def _ensure_brazil26_study(study_config: str | Path) -> str:
    cfg = load_config(study_config)
    study = str(cfg.study)
    token = study.casefold().replace("_", "-").replace(" ", "-")
    if "brazil" not in token and "brasil" not in token:
        raise ValueError(f"Brazil26 runtime refuses non-Brazil study config: study={study!r}")
    return study


def _brazil26_settings() -> Settings:
    settings = Settings()
    if settings.project_id in {"", "default"}:
        settings.project_id = PROJECT_ID
    if settings.project_id != PROJECT_ID:
        raise ValueError(
            f"LACLAUGPT_PROJECT_ID must be {PROJECT_ID!r} for Brazil26, "
            f"got {settings.project_id!r}"
        )
    if not settings.run_id:
        settings.run_id = f"brazil26-browser-{utc_stamp()}"
    return settings


def _read_env_file(path: Path) -> dict[str, str]:
    """Read the simple KEY=VALUE runtime env format used by install scripts."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = os.path.expandvars(value)
    return values


def _session_environment(
    *,
    repo_root: Path,
    study_config: Path,
    data_root: Path,
    env_file: Path | None = None,
) -> dict[str, str]:
    env = dict(os.environ)
    runtime_env = env_file or Path(
        env.get("LACLAUGPT_ENV_FILE", repo_root / "data/config/brazil26-localhost.env")
    )
    env.update(_read_env_file(runtime_env))
    env["LACLAUGPT_PROJECT_ID"] = PROJECT_ID
    env["LACLAUGPT_STUDY_CONFIG"] = str(study_config)
    env["BRAZIL26_CONFIG"] = str(study_config)
    env["LACLAUGPT_DATA_ROOT"] = str(data_root)
    env["LACLAUGPT_EXECUTION"] = "cli"
    env["LACLAUGPT_CALLER"] = "human-cli"
    return env


class JsonlDistributedMirror:
    """Continuously mirror newly appended canonical JSONL rows to remote storage."""

    def __init__(
        self,
        settings: Settings,
        *,
        study_config: str | Path,
        data_root: str | Path,
        interval_seconds: float = 1.0,
    ) -> None:
        self.settings = settings
        self.data_root = Path(data_root)
        self.normalized_dir = self.data_root / "normalized"
        self.state_path = self.data_root / ".brazil26-distributed-offsets.json"
        self.interval_seconds = max(float(interval_seconds), 0.1)
        self.sink = DistributedCaptureSink(settings)
        self.sink.assert_private_config(study_config)
        self._offsets = self._load_offsets()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_error = ""
        self.synced_total = 0

    def _load_offsets(self) -> dict[str, int]:
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}
        if not isinstance(raw, dict):
            return {}
        offsets: dict[str, int] = {}
        for key, value in raw.items():
            try:
                offsets[str(key)] = max(int(value), 0)
            except (TypeError, ValueError):
                continue
        return offsets

    def _save_offsets(self) -> None:
        self.data_root.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(self._offsets, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        tmp.replace(self.state_path)

    def scan_once(self) -> dict[str, int]:
        scanned = synced = 0
        if not self.normalized_dir.is_dir():
            return {"scanned": 0, "synced": 0}

        for path in sorted(self.normalized_dir.glob("*.jsonl")):
            key = path.name
            size = path.stat().st_size
            offset = min(self._offsets.get(key, 0), size)
            with path.open("r", encoding="utf-8") as handle:
                handle.seek(offset)
                while True:
                    line_start = handle.tell()
                    line = handle.readline()
                    if not line:
                        break
                    if not line.endswith("\n"):
                        handle.seek(line_start)
                        break
                    if not line.strip():
                        self._offsets[key] = handle.tell()
                        continue
                    scanned += 1
                    record = json.loads(line)
                    if not isinstance(record, dict):
                        raise ValueError(f"canonical row is not an object: {path}:{line_start}")
                    collection_id = str(record.get("collection_id") or PROJECT_ID)
                    if collection_id != PROJECT_ID:
                        raise ValueError(
                            f"Brazil26 mirror refuses collection_id={collection_id!r} in {path.name}"
                        )
                    record["collection_id"] = PROJECT_ID
                    self.sink.ingest(record)
                    synced += 1
                    self.synced_total += 1
                    self._offsets[key] = handle.tell()
                    self._save_offsets()
        return {"scanned": scanned, "synced": synced}

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.scan_once()
                self.last_error = ""
            except Exception as exc:  # noqa: BLE001
                self.last_error = str(exc)[:300]
            self._stop.wait(self.interval_seconds)

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run,
            name="brazil26-distributed-mirror",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(self.interval_seconds * 2, 2.0))
            self._thread = None


def run_backend(
    *,
    study_config: str,
    data_root: str,
    host: str,
    port: int,
    sync_interval: float,
) -> int:
    if host not in _LOOPBACK:
        raise ValueError("Brazil26 browser backend must bind to localhost/loopback")
    study = _ensure_brazil26_study(study_config)
    settings = _brazil26_settings()
    mirror = JsonlDistributedMirror(
        settings,
        study_config=study_config,
        data_root=data_root,
        interval_seconds=sync_interval,
    )
    remote = mirror.sink.smoke_check()
    print(
        json.dumps(
            {
                "status": "ready",
                "study": study,
                "project_id": settings.project_id,
                "backend": f"http://{host}:{port}",
                "remote": remote,
            },
            indent=2,
            sort_keys=True,
        ),
        flush=True,
    )

    mirror.scan_once()
    server = CaptureServer(study_config, data_root, host=host, port=port)
    mirror.start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        mirror.stop()
        try:
            mirror.scan_once()
        except Exception as exc:  # noqa: BLE001
            print(f"final distributed mirror failed: {exc}", flush=True)
        server.store.write_manifest(
            {
                "study": server.cfg.study,
                "project_id": settings.project_id,
                "run_id": settings.run_id,
                "stats": dict(server.stats),
                "seen_total": server.store.seen_count(),
                "distributed_synced_total": mirror.synced_total,
                "distributed_last_error": mirror.last_error,
            }
        )
        server.store.close()
        server.server_close()
    return 0


def run_check(*, study_config: str) -> int:
    study = _ensure_brazil26_study(study_config)
    settings = _brazil26_settings()
    sink = DistributedCaptureSink(settings)
    sink.assert_private_config(study_config)
    result: dict[str, Any] = {
        "status": "ok",
        "study": study,
        "project_id": settings.project_id,
        **sink.smoke_check(),
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def run_media(
    *,
    study_config: str,
    data_root: str,
    workers: int,
    limit: int,
) -> int:
    _ensure_brazil26_study(study_config)
    settings = _brazil26_settings()
    result = run_distributed_media(
        settings,
        study_config=study_config,
        data_root=data_root,
        workers=workers,
        limit=limit,
        use_lock=True,
    )
    result["study"] = PROJECT_ID
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if int(result.get("failed", 0)) == 0 else 1


def _ensure_cron(*, repo_root: Path, env: dict[str, str]) -> None:
    installer = repo_root / "scripts/install_cron_brazil26.sh"
    subprocess.run(["/bin/bash", str(installer)], cwd=repo_root, env=env, check=True)


def _wait_for_backend(host: str, port: int, process: subprocess.Popen[bytes]) -> None:
    endpoint = f"http://{host}:{port}/status"
    for _ in range(100):
        if process.poll() is not None:
            raise RuntimeError(f"Brazil26 backend exited early with status {process.returncode}")
        try:
            with urlopen(endpoint, timeout=0.25) as response:
                if 200 <= response.status < 500:
                    return
        except (OSError, URLError):
            time.sleep(0.1)
    raise RuntimeError(f"Brazil26 backend did not become ready at {endpoint}")


def _firefox_command(env: dict[str, str]) -> list[str]:
    configured = env.get("LACLAUGPT_FIREFOX_COMMAND", "").strip()
    if configured:
        command = shlex.split(configured)
    else:
        executable = shutil.which("firefox") or shutil.which("firefox.exe")
        if not executable:
            raise RuntimeError(
                "Firefox executable not found. Set LACLAUGPT_FIREFOX_COMMAND to the "
                "research Firefox command; Windows Firefox under WSL is supported."
            )
        command = [executable]

    profile_path = env.get("LACLAUGPT_FIREFOX_PROFILE_PATH", "").strip()
    profile_name = env.get("LACLAUGPT_FIREFOX_PROFILE", "").strip()
    if profile_path:
        command.extend(["--profile", profile_path])
    elif profile_name:
        command.extend(["-P", profile_name])
    return command


def run_researcher_session(
    *,
    study_config: str | Path | None = None,
    data_root: str | Path | None = None,
    host: str = "127.0.0.1",
    port: int = 8765,
    sync_interval: float = 1.0,
    install_cron: bool = True,
    launch_browser: bool = True,
    repo_root: Path | None = None,
) -> int:
    """Run the complete human-researcher Brazil26 collection session."""
    if host not in _LOOPBACK:
        raise ValueError("Brazil26 researcher session must bind to localhost/loopback")

    root = (repo_root or _repo_root()).resolve()
    config = _resolve_study_config(study_config, repo_root=root)
    _ensure_brazil26_study(config)

    chosen_data_root = Path(
        data_root or os.environ.get("LACLAUGPT_DATA_ROOT", root / "data")
    ).expanduser().resolve()
    chosen_data_root.mkdir(parents=True, exist_ok=True)
    env = _session_environment(repo_root=root, study_config=config, data_root=chosen_data_root)

    if install_cron:
        _ensure_cron(repo_root=root, env=env)

    command = [
        sys.executable,
        "-m",
        "laclaugpt_data_collection.brazil26_browser",
        "backend",
        "--study-config",
        str(config),
        "--data-root",
        str(chosen_data_root),
        "--host",
        host,
        "--port",
        str(port),
        "--sync-interval",
        str(sync_interval),
    ]
    backend = subprocess.Popen(command, cwd=root, env=env)
    try:
        _wait_for_backend(host, port, backend)
        if launch_browser:
            subprocess.Popen(_firefox_command(env), cwd=root, env=env)
        print(
            json.dumps(
                {
                    "status": "researcher-session-ready",
                    "study": PROJECT_ID,
                    "study_config": str(config),
                    "data_root": str(chosen_data_root),
                    "backend": f"http://{host}:{port}",
                    "cron_ensured": install_cron,
                    "browser_launched": launch_browser,
                },
                indent=2,
                sort_keys=True,
            ),
            flush=True,
        )
        return backend.wait()
    except KeyboardInterrupt:
        return 0
    finally:
        if backend.poll() is None:
            backend.terminate()
            try:
                backend.wait(timeout=5)
            except subprocess.TimeoutExpired:
                backend.kill()
                backend.wait()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="laclaugpt-brazil26",
        description="Start Brazil26 human-researcher collection, or use a low-level subcommand.",
    )
    parser.add_argument("--study-config", default=None, help="private Brazil26 study YAML")
    parser.add_argument("--data-root", default=None, help="existing Brazil26 data root")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--sync-interval", type=float, default=1.0)
    parser.add_argument("--no-cron", action="store_true", help="do not ensure the Brazil26 cron block")
    parser.add_argument("--no-browser", action="store_true", help="start backend without launching Firefox")

    sub = parser.add_subparsers(dest="command")
    backend = sub.add_parser("backend", help="run localhost Firefox capture with remote mirroring")
    backend.add_argument("--study-config", required=True)
    backend.add_argument("--data-root", required=True)
    backend.add_argument("--host", default="127.0.0.1")
    backend.add_argument("--port", type=int, default=8765)
    backend.add_argument("--sync-interval", type=float, default=1.0)

    check = sub.add_parser("check", help="verify Brazil26 identity and remote control plane")
    check.add_argument("--study-config", required=True)

    media = sub.add_parser("media", help="download pending Brazil26 media to S3/Allas")
    media.add_argument("--study-config", required=True)
    media.add_argument("--data-root", required=True)
    media.add_argument("--workers", type=int, default=4)
    media.add_argument("--limit", type=int, default=100)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command is None:
        try:
            return run_researcher_session(
                study_config=args.study_config,
                data_root=args.data_root,
                host=args.host,
                port=args.port,
                sync_interval=args.sync_interval,
                install_cron=not args.no_cron,
                launch_browser=not args.no_browser,
            )
        except (FileNotFoundError, RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
            print(f"Brazil26 startup failed: {exc}", file=sys.stderr)
            return 2
    if args.command == "backend":
        return run_backend(
            study_config=args.study_config,
            data_root=args.data_root,
            host=args.host,
            port=args.port,
            sync_interval=args.sync_interval,
        )
    if args.command == "check":
        return run_check(study_config=args.study_config)
    if args.command == "media":
        try:
            return run_media(
                study_config=args.study_config,
                data_root=args.data_root,
                workers=args.workers,
                limit=args.limit,
            )
        except MediaRunLockedError as exc:
            print(json.dumps({"status": "locked", "study": PROJECT_ID, "error": str(exc)}))
            return 75
    raise AssertionError(args.command)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
