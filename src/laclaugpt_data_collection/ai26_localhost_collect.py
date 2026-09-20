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


def collect_manifest(
    manifest_path: Path,
    study_path: Path,
    *,
    project_id: str = "ai26",
    collection_id: str = "ai26",
    machine: str = "laptop",
    run_id: str = "",
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

    bluesky_cap = int(os.getenv("LACLAUGPT_BLUESKY_PER_ACCOUNT_LIMIT", "20"))
    for row in manifest.get("bluesky_account", []):
        results.append(
            _run_plugin(
                plugins,
                store,
                "bluesky",
                row=row,
                config={"actor": row["handle"], "max_results": bluesky_cap},
                project_id=project_id,
                collection_id=collection_id,
                machine=machine,
                run_id=run_id,
            )
        )

    arxiv_cap = int(os.getenv("LACLAUGPT_ARXIV_PER_QUERY_LIMIT", "10"))
    for row in manifest.get("scholarly_query", []):
        services = {str(item).lower() for item in row.get("services", [])}
        if "arxiv" not in services:
            continue
        results.append(
            _run_plugin(
                plugins,
                store,
                "arxiv",
                row=row,
                config={"query": row["query"], "max_results": arxiv_cap},
                project_id=project_id,
                collection_id=collection_id,
                machine=machine,
                run_id=run_id,
            )
        )

    return {
        "project_id": project_id,
        "collection_id": collection_id,
        "machine": machine,
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
    args = parser.parse_args(argv)
    result = collect_manifest(
        Path(args.source_manifest),
        Path(args.study_config),
        project_id=args.project_id,
        collection_id=args.collection_id,
        machine=args.machine,
        run_id=args.run_id,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
