"""Brazil26 Firefox runtime using the shared localhost collector and distributed storage.

The browser extension always talks to a loopback-only capture server. Canonical
JSONL is retained locally as a recovery/debug fallback and mirrored continuously
to the configured MongoDB/Redis/S3 (CSC Allas) backends. Media downloading stays
out of the interactive request path and is handled by the existing distributed
media runner.
"""
from __future__ import annotations

import argparse
import json
import threading
import time
from pathlib import Path
from typing import Any

from .capture_server import CaptureServer
from .config import Settings
from .distributed_capture import DistributedCaptureSink
from .distributed_media_runner import run_distributed_media
from .store import utc_stamp
from .study import load_config

PROJECT_ID = "brazil26"
_LOOPBACK = {"127.0.0.1", "localhost", "::1"}


def _ensure_brazil26_study(study_config: str | Path) -> str:
    cfg = load_config(study_config)
    study = str(cfg.study)
    token = study.casefold().replace("_", "-").replace(" ", "-")
    if "brazil" not in token and "brasil" not in token:
        raise ValueError(
            f"Brazil26 runtime refuses non-Brazil study config: study={study!r}"
        )
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


class JsonlDistributedMirror:
    """Continuously mirror newly appended canonical JSONL rows to remote storage.

    Byte offsets are persisted under the Brazil26 data root. An offset advances
    only after a remote ingest succeeds, so transient MongoDB/Redis/S3 failures
    remain retryable without losing a record. The remote sink is idempotent at
    the canonical record/object layer.
    """

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
                        # Writer may still be appending this line. Retry next scan.
                        handle.seek(line_start)
                        break
                    if not line.strip():
                        self._offsets[key] = handle.tell()
                        continue
                    scanned += 1
                    record = json.loads(line)
                    if not isinstance(record, dict):
                        raise ValueError(f"canonical row is not an object: {path}:{line_start}")
                    record.setdefault("collection_id", PROJECT_ID)
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

    # Flush any backlog from an earlier interrupted session before accepting new capture.
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
    )
    result["study"] = PROJECT_ID
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if int(result.get("failed", 0)) == 0 else 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m laclaugpt_data_collection.brazil26_browser")
    sub = parser.add_subparsers(dest="command", required=True)

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
        return run_media(
            study_config=args.study_config,
            data_root=args.data_root,
            workers=args.workers,
            limit=args.limit,
        )
    raise AssertionError(args.command)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
