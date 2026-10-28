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
from .config import Settings
from .distributed_jobs import (
    LOCALHOST_CAPABILITIES,
    dispatch_claim,
    dispatch_finish,
    job_identity,
)
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


def _row_name(kind: str, row: dict[str, Any]) -> str:
    """The stable name a manifest row contributes to its job identity.

    The manifest's ``name`` field wins, because that is the field the Laskin runner enqueues with.
    Deriving the identity from ``handle``/``query`` instead makes the same source two different queue
    entries on two hosts — which is the duplication this change exists to remove.
    """
    candidate = row.get("name")
    if not candidate:
        candidate = row.get("handle") if kind == "bluesky_account" else row.get("query")
    return str(candidate or kind)


def plan_jobs(
    manifest: dict[str, Any],
    *,
    dispatch: Any | None = None,
    worker_id: str = "localhost-cron",
    max_jobs: int = 12,
    lease_seconds: int = 1800,
) -> tuple[list[tuple[str, dict[str, Any]]], list[dict[str, Any]]]:
    """Which manifest rows this host runs this tick (#378).

    Without a dispatcher the answer is "all of them", which is the pre-#378 behaviour and the reason
    two hosts could collect the same source. With a dispatcher the answer is whatever the shared
    queue grants, and only for kinds this orchestrator can execute: a browser kind is never claimed,
    because X capture is the Firefox extension's path and a claim here would park it on a lease.
    """
    planned: list[tuple[str, dict[str, Any]]] = [
        ("bluesky_account", row) for row in manifest.get("bluesky_account", [])
    ] + [("scholarly_query", row) for row in manifest.get("scholarly_query", [])]
    total = len(planned)
    if dispatch is None:
        return planned, [], total
    claimable = []
    for kind, row in planned:
        name = _row_name(kind, row)
        claimable.append({**row, "kind": kind, "name": name,
                          "job_id": job_identity({"kind": kind, "name": name})})
    claimed = dispatch_claim(
        dispatch, claimable, worker_id=worker_id, max_jobs=max_jobs, lease_seconds=lease_seconds,
        capabilities=LOCALHOST_CAPABILITIES,
        executable_kinds={"bluesky_account", "scholarly_query"},
    )
    granted = {str(job.get("_job_id")) for job in claimed}
    selected = [
        (kind, row) for kind, row in planned
        if job_identity({"kind": kind, "name": _row_name(kind, row)}) in granted
    ]
    return selected, claimed, total


def collect_manifest(
    manifest_path: Path,
    study_path: Path,
    *,
    project_id: str = "ai26",
    collection_id: str = "ai26",
    machine: str = "laptop",
    run_id: str = "",
    dispatch: Any | None = None,
    worker_id: str = "localhost-cron",
    dispatch_lease_seconds: int = 1800,
    max_jobs: int = 12,
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

    planned, results_claimed, jobs_planned = plan_jobs(
        manifest, dispatch=dispatch, worker_id=worker_id, max_jobs=max_jobs,
        lease_seconds=dispatch_lease_seconds,
    )

    claimed_by_id = {str(job.get("_job_id")): job for job in results_claimed}

    def settle(kind: str, row: dict[str, Any], outcome: dict[str, Any]) -> None:
        """Settle the queue entry this row holds; a no-op in manifest mode."""
        if dispatch is None:
            return
        job_id = job_identity({"kind": kind, "name": _row_name(kind, row)})
        job = claimed_by_id.get(job_id)
        if job is not None:
            dispatch_finish(dispatch, job, outcome, worker_id=worker_id)

    bluesky_cap = int(os.getenv("LACLAUGPT_BLUESKY_PER_ACCOUNT_LIMIT", "20"))
    for row in [row for kind, row in planned if kind == "bluesky_account"]:
        try:
            results.append(_run_plugin(
                plugins, store, "bluesky", row=row,
                config={"actor": row["handle"], "max_results": bluesky_cap},
                project_id=project_id, collection_id=collection_id, machine=machine,
                run_id=run_id,
            ))
        except Exception as exc:  # noqa: BLE001 - one source must not abort the pass
            # A claimed job is released with its reason, so it does not sit on a dead lease.
            results.append({"plugin": "bluesky", "source": _row_name("bluesky_account", row),
                            "status": "error", "reason": f"{type(exc).__name__}: {exc}"[:300]})
            settle("bluesky_account", row, {"status": "error",
                                            "reason": f"{type(exc).__name__}: {exc}"[:300]})
            continue
        settle("bluesky_account", row, {"status": "ok"})

    arxiv_cap = int(os.getenv("LACLAUGPT_ARXIV_PER_QUERY_LIMIT", "10"))
    for row in [row for kind, row in planned if kind == "scholarly_query"]:
        services = {str(item).lower() for item in row.get("services", [])}
        if "arxiv" not in services:
            # Not an arXiv query: nothing to run, so the queue entry goes back rather than dying.
            settle("scholarly_query", row, {"status": "deferred", "reason": "not an arxiv query"})
            continue
        try:
            results.append(_run_plugin(
                plugins, store, "arxiv", row=row,
                config={"query": row["query"], "max_results": arxiv_cap},
                project_id=project_id, collection_id=collection_id, machine=machine,
                run_id=run_id,
            ))
        except Exception as exc:  # noqa: BLE001
            results.append({"plugin": "arxiv", "source": _row_name("scholarly_query", row),
                            "status": "error", "reason": f"{type(exc).__name__}: {exc}"[:300]})
            settle("scholarly_query", row, {"status": "error",
                                            "reason": f"{type(exc).__name__}: {exc}"[:300]})
            continue
        settle("scholarly_query", row, {"status": "ok"})

    return {
        "project_id": project_id,
        "collection_id": collection_id,
        "machine": machine,
        "worker_id": worker_id,
        "dispatch": "mongo" if dispatch is not None else "manifest",
        "jobs_planned": jobs_planned,
        "jobs_claimed": len(results_claimed),
        "publication_date_floor": not_before.date().isoformat(),
        "runs": results,
        "skipped_before_window": store.skipped_before_window,
        "unresolved_publication_time": store.unresolved_publication_time,
        "notes": [
            "RSS is executed by the same shell wrapper before this Phase 1 plugin pass.",
            "X/browser capture remains manual and is never scheduled.",
            "Mastodon account rows are not run until the canonical plugin supports account-target collection.",
            "YouTube manifest rows name channels rather than canonical video URLs, so transcript collection is not guessed here.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ai26-localhost-collect")
    parser.add_argument("--source-manifest", required=True)
    parser.add_argument("--study-config", required=True)
    parser.add_argument("--project-id", default="ai26")
    parser.add_argument("--collection-id", default="ai26")
    parser.add_argument("--machine", default=os.getenv("LACLAUGPT_MACHINE", "laptop"))
    parser.add_argument("--run-id", default=os.getenv("LACLAUGPT_RUN_ID", ""))
    parser.add_argument("--worker-id", default=os.getenv("LACLAUGPT_WORKER_ID", "localhost-cron"))
    parser.add_argument("--dispatch-mongo", action="store_true",
                        help="claim this host's share from the shared MongoDB queue (#378)")
    parser.add_argument("--dispatch-lease-seconds", type=int, default=1800)
    parser.add_argument("--max-jobs", type=int, default=12)
    args = parser.parse_args(argv)
    dispatch = None
    if args.dispatch_mongo:
        from pymongo import MongoClient

        from .distributed import ProjectNamespace
        from .distributed_jobs import JobLeaseStore

        settings = Settings()
        if not settings.mongodb_uri:
            parser.error("--dispatch-mongo needs a MongoDB URI in the settings")
        client = MongoClient(settings.mongodb_uri,
                             serverSelectionTimeoutMS=settings.mongodb_connect_timeout_ms,
                             connect=False)
        dispatch = JobLeaseStore(
            client[settings.mongodb_database][
                ProjectNamespace(project_id=args.project_id).mongo_collection("jobs")]
        )
        dispatch.ensure_indexes()
    result = collect_manifest(
        Path(args.source_manifest),
        Path(args.study_config),
        project_id=args.project_id,
        collection_id=args.collection_id,
        machine=args.machine,
        run_id=args.run_id,
        dispatch=dispatch,
        worker_id=args.worker_id,
        dispatch_lease_seconds=args.dispatch_lease_seconds,
        max_jobs=args.max_jobs,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
