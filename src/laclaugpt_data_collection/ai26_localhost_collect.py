"""Bounded Phase 1 AI26 non-browser collection for the researcher localhost.

This orchestrator deliberately reuses the canonical Phase 1 plugin registry and record
store. It adds only study/runtime orchestration: manifest expansion, the AI26 publication
window, bounded source budgets, and sampling provenance. Browser/X capture remains manual.
"""
from __future__ import annotations

import argparse
import json
import os
import tomllib
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import yaml

from .collectors.base import CollectionResult
from .distributed_jobs import (
    JobLeaseStore,
    dispatch_claim,
    dispatch_finish,
    queue_snapshot,
    requires_browser,
)
from .config import Settings
from .factory import build_record_store
from .models import CanonicalRecord, CollectionProvenance
from .plugins import CollectionContext, CollectionRunner, PluginRegistry, default_registry
from .storage.base import RecordStore


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        try:
            parsed = datetime.combine(date.fromisoformat(text), datetime.min.time())
        except ValueError:
            return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


class _WindowedStore:
    """Filter pre-window records while retaining unresolved publication times."""

    def __init__(self, store: RecordStore, not_before: datetime) -> None:
        self.store = store
        self.not_before = not_before
        self.skipped_before_window = 0
        self.unresolved_publication_time = 0

    def contains(self, source_url: str) -> bool:
        return self.store.contains(source_url)

    def upsert(self, record: CanonicalRecord) -> None:
        published = _parse_timestamp(record.source.created_at)
        if published is not None and published < self.not_before:
            self.skipped_before_window += 1
            return
        if published is None:
            self.unresolved_publication_time += 1
            record.source.raw_metadata.setdefault("publication_time_unresolved", True)
        self.store.upsert(record)

    def upsert_many(self, records: Any) -> None:
        for record in records:
            self.upsert(record)


class _SamplingPlugin:
    """Decorate one canonical plugin run with collection-only sampling provenance."""

    def __init__(
        self,
        plugin: Any,
        *,
        source_family: str,
        priority: str,
        machine: str,
    ) -> None:
        self._plugin = plugin
        self.spec = plugin.spec
        self.source_family = source_family
        self.priority = priority
        self.machine = machine

    def collect(self, context: CollectionContext) -> CollectionResult:
        result = self._plugin.collect(context)
        for record in result.records:
            if self.source_family:
                record.source.raw_metadata.setdefault(
                    "sampling_source_family", self.source_family
                )
            if self.priority:
                record.source.raw_metadata.setdefault("sampling_priority", self.priority)
            record.source.raw_metadata.setdefault("collection_machine", self.machine)
            record.provenance.append(
                CollectionProvenance(
                    run_id=context.run_id,
                    module="ai26-localhost-orchestrator",
                    transformations=["sampling-provenance-only"],
                    metadata={
                        "collection_id": context.collection_id,
                        "project_id": context.project_id,
                        "arena": context.arena,
                        "machine": self.machine,
                        "sampling_source_family": self.source_family,
                        "sampling_priority": self.priority,
                        "ideology_ground_truth": False,
                    },
                )
            )
        return result


def _single_plugin_registry(plugin: Any, row: dict[str, Any], machine: str) -> PluginRegistry:
    registry = PluginRegistry()
    registry.register(
        _SamplingPlugin(
            plugin,
            source_family=str(row.get("source_family") or ""),
            priority=str(row.get("priority") or ""),
            machine=machine,
        )
    )
    return registry


def _run_plugin(
    plugins: PluginRegistry,
    store: RecordStore,
    plugin_id: str,
    *,
    row: dict[str, Any],
    config: dict[str, Any],
    project_id: str,
    collection_id: str,
    machine: str,
    run_id: str,
) -> dict[str, Any]:
    plugin = plugins.get(plugin_id)
    registry = _single_plugin_registry(plugin, row, machine)
    runner = CollectionRunner(registry, store)
    context = CollectionContext(
        config=config,
        project_id=project_id,
        collection_id=collection_id,
        arena=str(row.get("arena") or ""),
        run_id=run_id,
    )
    result = runner.run(plugin_id, context)
    return {
        "plugin": plugin_id,
        "source": str(row.get("name") or row.get("handle") or row.get("query") or ""),
        "records_seen": result.records_seen,
        "records_written": result.records_written,
        "duplicates_skipped": result.duplicates_skipped,
        "warnings": result.warnings,
    }


def _manifest_jobs(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """The manifest rows this collector can actually execute, as queue jobs.

    Identity is ``(kind, name)`` — the same pair :func:`distributed_jobs.job_identity` uses — so
    re-reading the manifest on another host addresses the same queue entry.
    """
    jobs: list[dict[str, Any]] = []
    for row in manifest.get("bluesky_account", []):
        jobs.append({"kind": "bluesky_account", "name": str(row.get("handle") or ""), "row": row})
    for row in manifest.get("scholarly_query", []):
        services = {str(item).lower() for item in row.get("services", [])}
        if "arxiv" in services:
            jobs.append({"kind": "scholarly_query", "name": str(row.get("query") or ""), "row": row})
    return jobs


def _run_job(
    plugins: PluginRegistry,
    store: RecordStore,
    job: dict[str, Any],
    *,
    project_id: str,
    collection_id: str,
    machine: str,
    run_id: str,
) -> dict[str, Any]:
    kind, row = str(job["kind"]), dict(job["row"])
    if kind == "bluesky_account":
        cap = int(os.getenv("LACLAUGPT_BLUESKY_PER_ACCOUNT_LIMIT", "20"))
        return _run_plugin(plugins, store, "bluesky", row=row,
                           config={"actor": row["handle"], "max_results": cap},
                           project_id=project_id, collection_id=collection_id,
                           machine=machine, run_id=run_id)
    if kind == "scholarly_query":
        cap = int(os.getenv("LACLAUGPT_ARXIV_PER_QUERY_LIMIT", "10"))
        return _run_plugin(plugins, store, "arxiv", row=row,
                           config={"query": row["query"], "max_results": cap},
                           project_id=project_id, collection_id=collection_id,
                           machine=machine, run_id=run_id)
    raise ValueError(f"localhost collector has no executor for job kind {kind!r}")


def collect_manifest(
    manifest_path: Path,
    study_path: Path,
    *,
    project_id: str = "ai26",
    collection_id: str = "ai26",
    machine: str = "laptop",
    run_id: str = "",
    dispatch: JobLeaseStore | None = None,
    worker_id: str = "",
    max_jobs: int = 10,
    lease_seconds: int = 1800,
) -> dict[str, Any]:
    manifest = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    study = yaml.safe_load(study_path.read_text(encoding="utf-8")) or {}
    floor = (
        study.get("collection_policy", {}).get("publication_date_floor")
        or study.get("window", {}).get("start")
        or "2026-09-01"
    )
    not_before = _parse_timestamp(str(floor))
    if not_before is None:
        raise ValueError(f"invalid AI26 publication date floor: {floor!r}")

    settings = Settings()
    base_store = build_record_store(settings)
    store = _WindowedStore(base_store, not_before)
    plugins = default_registry()
    results: list[dict[str, Any]] = []

    jobs = _manifest_jobs(manifest)
    if dispatch is not None:
        # #378: the shared queue decides which jobs this host runs. The manifest is enqueued
        # idempotently first, so a restart follows the queue instead of accumulating copies.
        payload = [
            {"kind": job["kind"], "name": job["name"],
             **{k: v for k, v in job["row"].items() if k not in {"job_id", "id", "kind"}}}
            for job in jobs
        ]
        claimed = dispatch_claim(
            dispatch,
            payload,
            worker_id=worker_id,
            max_jobs=max_jobs,
            lease_seconds=lease_seconds,
            capabilities={"non_browser"},
        )
        selected = [
            {"kind": c.get("kind", ""), "name": c.get("name", ""), "row": c, "_job_id": c.get("_job_id")}
            for c in claimed
        ]
        # The CLI cannot drive Firefox (#258 keeps browser navigation user-controlled), so a
        # browser job must never be executed here even if one is somehow handed over.
        offending = [j["kind"] for j in selected if requires_browser(j["kind"])]
        if offending:
            raise RuntimeError(f"non-browser localhost worker was offered browser jobs: {offending}")
    else:
        selected = jobs

    for job in selected:
        try:
            result = _run_job(plugins, store, job, project_id=project_id,
                              collection_id=collection_id, machine=machine, run_id=run_id)
            result["status"] = "ok"
        except Exception as exc:  # settle the lease instead of holding it until expiry
            result = {"plugin": _plugin_for(job["kind"]), "source": job["name"],
                      "records_seen": 0, "records_written": 0, "duplicates_skipped": 0,
                      "warnings": [], "status": "error", "error": str(exc)}
        results.append(result)
        if dispatch is not None and job.get("_job_id"):
            dispatch_finish(
                dispatch,
                {"_job_id": job["_job_id"]},
                {"status": result["status"], "reason": result.get("error", "")},
                worker_id=worker_id,
            )

    return {
        "project_id": project_id,
        "collection_id": collection_id,
        "machine": machine,
        "publication_date_floor": not_before.date().isoformat(),
        "runs": results,
        "skipped_before_window": store.skipped_before_window,
        "unresolved_publication_time": store.unresolved_publication_time,
        "dispatch": "mongodb" if dispatch is not None else "manifest",
        "notes": [
            "RSS is executed by the same shell wrapper before this Phase 1 plugin pass.",
            "X/browser capture remains manual and is never scheduled; this worker declares "
            "only the non_browser capability, so the queue cannot hand it browser work.",
            "Mastodon account rows are not run until the canonical plugin supports account-target collection.",
            "YouTube manifest rows name channels rather than canonical video URLs, so transcript collection is not guessed here.",
        ],
    }


def _plugin_for(kind: str) -> str:
    return {"bluesky_account": "bluesky", "scholarly_query": "arxiv"}.get(kind, kind)


def queue_health(dispatch: JobLeaseStore, *, capabilities) -> dict[str, Any]:
    """Read-only queue snapshot for this worker; never mutates a job."""
    docs = list(dispatch.jobs.find({}, {"status": 1, "kind": 1}))
    snapshot = queue_snapshot(docs, capabilities)
    snapshot["worker_kind"] = "localhost"
    snapshot["browser_capture"] = "manual (never scheduled)"
    return snapshot


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ai26-localhost-collect")
    parser.add_argument("--source-manifest")
    parser.add_argument("--study-config")
    parser.add_argument("--project-id", default="ai26")
    parser.add_argument("--collection-id", default="ai26")
    parser.add_argument("--machine", default=os.getenv("LACLAUGPT_MACHINE", "laptop"))
    parser.add_argument("--run-id", default=os.getenv("LACLAUGPT_RUN_ID", ""))
    parser.add_argument("--dispatch-mongo", action="store_true",
                        help="claim non-browser jobs from the shared MongoDB queue (#378)")
    parser.add_argument("--worker-id", default=os.getenv("LACLAUGPT_WORKER_ID", ""))
    parser.add_argument("--max-jobs", type=int, default=10)
    parser.add_argument("--lease-seconds", type=int, default=1800)
    parser.add_argument("--status", action="store_true", help="print this host's queue health and exit")
    args = parser.parse_args(argv)

    if args.status:
        return _print_status(args)
    if not args.source_manifest or not args.study_config:
        parser.error("--source-manifest and --study-config are required unless --status is used")

    dispatch = _dispatch_store() if args.dispatch_mongo else None
    if args.dispatch_mongo and dispatch is None:
        return 2
    result = collect_manifest(
        Path(args.source_manifest),
        Path(args.study_config),
        project_id=args.project_id,
        collection_id=args.collection_id,
        machine=args.machine,
        run_id=args.run_id,
        dispatch=dispatch,
        worker_id=args.worker_id or _default_worker_id(args.machine),
        max_jobs=args.max_jobs,
        lease_seconds=args.lease_seconds,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def _default_worker_id(machine: str) -> str:
    import socket
    host = socket.gethostname().split(".")[0] or "localhost"
    return f"{machine}-{host}"


def _dispatch_store() -> JobLeaseStore | None:
    """Open the shared queue; return None (with a reason) when MongoDB is not configured."""
    from pymongo import MongoClient

    from .distributed import ProjectNamespace

    settings = Settings()
    if not settings.mongodb_uri:
        print(json.dumps({"error": "no MongoDB URI in the runtime settings; set "
                                   "LACLAUGPT_MONGODB_URI via the private env file"}, indent=2))
        return None
    client = MongoClient(settings.mongodb_uri,
                         serverSelectionTimeoutMS=settings.mongodb_connect_timeout_ms)
    collection = client[settings.mongodb_database][
        ProjectNamespace(project_id=settings.project_id).mongo_collection("jobs")
    ]
    return JobLeaseStore(collection)


def _print_status(args) -> int:
    dispatch = _dispatch_store()
    if dispatch is None:
        return 2
    print(json.dumps(queue_health(dispatch, capabilities={"non_browser"}), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
