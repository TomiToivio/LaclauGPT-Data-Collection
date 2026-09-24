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
import signal
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
from .models import CanonicalRecord
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


def _brazil26_settings(*, env_file: str | Path | None = None) -> Settings:
    """Load Brazil26 settings without reading an ambient dotenv by default."""
    settings = Settings(_env_file=env_file)
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
    mirror: JsonlDistributedMirror | None = None
    remote: dict[str, Any] = {"status": "disabled", "reason": "local-only profile"}
    if settings.distributed_requested:
        mirror = JsonlDistributedMirror(
            settings,
            study_config=study_config,
            data_root=data_root,
            interval_seconds=sync_interval,
        )
        remote = {"status": "enabled", **mirror.sink.smoke_check()}
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

    if mirror is not None:
        mirror.scan_once()
    server = CaptureServer(study_config, data_root, host=host, port=port)
    if mirror is not None:
        mirror.start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if mirror is not None:
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
                "distributed_enabled": mirror is not None,
                "distributed_synced_total": mirror.synced_total if mirror is not None else 0,
                "distributed_last_error": mirror.last_error if mirror is not None else "",
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
        # A complete executable path may contain spaces (notably Windows Firefox
        # from WSL). A command with arguments still uses shell-style quoting.
        command = [configured] if Path(configured).is_file() else shlex.split(configured)
        if not command:
            raise RuntimeError("LACLAUGPT_FIREFOX_COMMAND is empty")
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


def _check_firefox_command(command: list[str], *, env: dict[str, str]) -> None:
    """Probe the executable, not just its presence on PATH (e.g. a broken snap shim)."""
    executable = command[0]
    if not (Path(executable).is_file() or shutil.which(executable)):
        raise RuntimeError("Firefox executable is not available; configure LACLAUGPT_FIREFOX_COMMAND")
    try:
        probe = subprocess.run(
            [executable, "--version"],
            env=env,
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("Firefox executable failed its --version probe") from exc
    if probe.returncode != 0:
        raise RuntimeError(
            "Firefox executable is unusable (version probe exited "
            f"{probe.returncode}); set LACLAUGPT_FIREFOX_COMMAND to a working browser"
        )


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
    session_path = _session_file(chosen_data_root)
    previous_sigterm: Any = None
    if hasattr(signal, "SIGTERM"):
        previous_sigterm = signal.getsignal(signal.SIGTERM)

        def _stop_signal(_signum: int, _frame: Any) -> None:
            raise KeyboardInterrupt

        signal.signal(signal.SIGTERM, _stop_signal)
    try:
        _wait_for_backend(host, port, backend)
        _write_session(
            chosen_data_root,
            backend_pid=backend.pid,
            host=host,
            port=port,
            study_config=config,
        )
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
        session_path.unlink(missing_ok=True)
        if backend.poll() is None:
            backend.terminate()
            try:
                backend.wait(timeout=5)
            except subprocess.TimeoutExpired:
                backend.kill()
                backend.wait()
        if previous_sigterm is not None:
            signal.signal(signal.SIGTERM, previous_sigterm)



def _session_file(data_root: str | Path) -> Path:
    return Path(data_root) / ".brazil26-session.json"


def _load_session(data_root: str | Path) -> dict[str, Any]:
    path = _session_file(data_root)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_session(
    data_root: str | Path, *, backend_pid: int, host: str, port: int, study_config: Path
) -> None:
    path = _session_file(data_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "project_id": PROJECT_ID,
                "pid": os.getpid(),
                "backend_pid": backend_pid,
                "backend": f"http://{host}:{port}",
                "study_config": str(study_config),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _backend_status(host: str, port: int) -> dict[str, Any] | None:
    try:
        with urlopen(f"http://{host}:{port}/status", timeout=0.5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def run_preflight(
    *,
    study_config: str | Path | None = None,
    data_root: str | Path | None = None,
    require_browser: bool = True,
    repo_root: Path | None = None,
) -> int:
    root = (repo_root or _repo_root()).resolve()
    problems: list[str] = []
    warnings: list[str] = []
    try:
        config = _resolve_study_config(study_config, repo_root=root)
        study = _ensure_brazil26_study(config)
    except (FileNotFoundError, ValueError) as exc:
        config = Path(study_config or "")
        study = ""
        problems.append(str(exc))

    chosen_data_root = Path(
        data_root or os.environ.get("LACLAUGPT_DATA_ROOT", root / "data")
    ).expanduser().resolve()
    try:
        chosen_data_root.mkdir(parents=True, exist_ok=True)
        probe = chosen_data_root / ".brazil26-write-test"
        probe.write_text("ok\n", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        problems.append(f"data root is not writable: {chosen_data_root}: {exc}")

    env_file = Path(
        os.environ.get("LACLAUGPT_ENV_FILE", root / "data/config/brazil26-localhost.env")
    )
    runtime = _read_env_file(env_file)
    configured_project = runtime.get("LACLAUGPT_PROJECT_ID", PROJECT_ID)
    if configured_project != PROJECT_ID:
        problems.append(
            f"runtime env must use LACLAUGPT_PROJECT_ID={PROJECT_ID}, got {configured_project!r}"
        )
    if not env_file.is_file():
        warnings.append(
            f"runtime env not found: {env_file}; copy configs/brazil26.env.example for explicit settings"
        )

    extension = root / "browser/firefox/manifest.json"
    if not extension.is_file():
        problems.append(f"Firefox extension manifest missing: {extension}")

    browser_command: list[str] = []
    if require_browser:
        env = dict(os.environ)
        env.update(runtime)
        try:
            browser_command = _firefox_command(env)
            _check_firefox_command(browser_command, env=env)
        except RuntimeError as exc:
            problems.append(str(exc))

    distributed_keys = (
        runtime.get("LACLAUGPT_RECORD_BACKEND") == "mongodb"
        or runtime.get("LACLAUGPT_OBJECT_BACKEND") == "s3"
        or runtime.get("LACLAUGPT_CACHE_BACKEND") == "redis"
        or runtime.get("LACLAUGPT_DISTRIBUTED_CONFIG_BACKEND") == "redis"
    )
    result = {
        "status": "ok" if not problems else "invalid",
        "project_id": PROJECT_ID,
        "study": study,
        "study_config": str(config) if config else "",
        "data_root": str(chosen_data_root),
        "env_file": str(env_file),
        "extension_manifest": str(extension),
        "browser_command": browser_command,
        "distributed_requested": bool(distributed_keys),
        "problems": problems,
        "warnings": warnings,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if not problems else 2


def run_status(*, data_root: str | Path, host: str, port: int) -> int:
    root = Path(data_root).expanduser().resolve()
    session = _load_session(root)
    live = _backend_status(host, port)
    normalized = root / "normalized"
    files = sorted(normalized.glob("*.jsonl")) if normalized.is_dir() else []
    rows = 0
    for path in files:
        try:
            with path.open("r", encoding="utf-8") as handle:
                rows += sum(1 for line in handle if line.strip())
        except OSError:
            continue
    result = {
        "status": "running" if live is not None else "stopped",
        "project_id": PROJECT_ID,
        "backend": f"http://{host}:{port}",
        "backend_status": live,
        "session": session,
        "data_root": str(root),
        "normalized_files": len(files),
        "normalized_rows": rows,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if live is not None else 3


def run_stop(*, data_root: str | Path) -> int:
    root = Path(data_root).expanduser().resolve()
    path = _session_file(root)
    session = _load_session(root)
    pid = int(session.get("pid") or 0)
    if pid <= 0:
        print(json.dumps({"status": "stopped", "project_id": PROJECT_ID, "message": "no active session"}))
        return 0
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        path.unlink(missing_ok=True)
        print(json.dumps({"status": "stopped", "project_id": PROJECT_ID, "message": "stale session cleared"}))
        return 0
    except OSError as exc:
        print(json.dumps({"status": "error", "project_id": PROJECT_ID, "error": str(exc)}))
        return 2
    print(json.dumps({"status": "stopping", "project_id": PROJECT_ID, "pid": pid}))
    return 0


def run_validate(*, data_root: str | Path) -> int:
    root = Path(data_root).expanduser().resolve()
    normalized = root / "normalized"
    errors: list[str] = []
    checked = 0
    urls: set[str] = set()
    duplicates = 0
    files = sorted(normalized.glob("*.jsonl")) if normalized.is_dir() else []
    for path in files:
        try:
            handle = path.open("r", encoding="utf-8")
        except OSError as exc:
            errors.append(f"{path}: {exc}")
            continue
        with handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                checked += 1
                try:
                    payload = json.loads(line)
                    if not isinstance(payload, dict):
                        raise ValueError("row is not a JSON object")
                    collection_id = payload.pop("collection_id", None)
                    if collection_id not in (None, "", PROJECT_ID):
                        raise ValueError(f"cross-study collection_id={collection_id!r}")
                    record = CanonicalRecord.model_validate(payload)
                    if record.source_url in urls:
                        duplicates += 1
                    urls.add(record.source_url)
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{path.name}:{line_number}: {exc}")
    result = {
        "status": "ok" if not errors else "invalid",
        "project_id": PROJECT_ID,
        "data_root": str(root),
        "files": len(files),
        "records_checked": checked,
        "duplicate_source_urls": duplicates,
        "errors": errors[:50],
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if not errors else 2

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

    preflight = sub.add_parser("preflight", help="check localhost researcher setup before collection")
    preflight.add_argument("--study-config", default=None)
    preflight.add_argument("--data-root", default=None)
    preflight.add_argument("--no-browser", action="store_true")

    status = sub.add_parser("status", help="show the localhost Brazil26 session and data status")
    status.add_argument("--data-root", default="./data")
    status.add_argument("--host", default="127.0.0.1")
    status.add_argument("--port", type=int, default=8765)

    stop = sub.add_parser("stop", help="stop the active localhost Brazil26 researcher session")
    stop.add_argument("--data-root", default="./data")

    validate = sub.add_parser("validate", help="validate local canonical JSONL for analysis handoff")
    validate.add_argument("--data-root", default="./data")

    check = sub.add_parser("check", help="verify Brazil26 identity and configured remote control plane")
    check.add_argument("--study-config", required=True)

    media = sub.add_parser("media", help="download pending Brazil26 media to configured storage")
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
    if args.command == "preflight":
        return run_preflight(
            study_config=args.study_config,
            data_root=args.data_root,
            require_browser=not args.no_browser,
        )
    if args.command == "status":
        return run_status(data_root=args.data_root, host=args.host, port=args.port)
    if args.command == "stop":
        return run_stop(data_root=args.data_root)
    if args.command == "validate":
        return run_validate(data_root=args.data_root)
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
