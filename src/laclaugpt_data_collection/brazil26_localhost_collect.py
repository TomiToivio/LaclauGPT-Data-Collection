"""Bounded Brazil26 non-browser collection for a researcher localhost.

RSS remains the primary unattended source family. This module adds a second
canonical plugin pass for source rows that are directly executable without
inventing political targets. In particular, YouTube collection runs only when
an approved manifest provides explicit video URLs; channel homepages are not
expanded or guessed.
"""
from __future__ import annotations

import argparse
import json
import os
import tomllib
from pathlib import Path
from typing import Any

from .collectors.base import CollectionResult
from .config import Settings
from .factory import build_record_store
from .models import CollectionProvenance
from .plugins import CollectionContext, CollectionRunner, PluginRegistry, default_registry
from .storage.base import RecordStore


class _SamplingPlugin:
    """Decorate one canonical plugin run with collection-only provenance."""

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
                    module="brazil26-localhost-orchestrator",
                    transformations=["sampling-provenance-only"],
                    metadata={
                        "collection_id": context.collection_id,
                        "project_id": context.project_id,
                        "arena": context.arena,
                        "machine": self.machine,
                        "sampling_source_family": self.source_family,
                        "sampling_priority": self.priority,
                        "political_label_ground_truth": False,
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


def _run_youtube(
    plugins: PluginRegistry,
    store: RecordStore,
    row: dict[str, Any],
    *,
    project_id: str,
    collection_id: str,
    machine: str,
    run_id: str,
) -> dict[str, Any]:
    urls = row.get("video_urls") or []
    if not isinstance(urls, list) or not all(isinstance(url, str) for url in urls):
        raise ValueError("Brazil26 youtube_source.video_urls must be a list of strings")

    plugin = plugins.get("youtube")
    runner = CollectionRunner(_single_plugin_registry(plugin, row, machine), store)
    context = CollectionContext(
        config={
            "video_urls": urls,
            "page_size": int(os.getenv("LACLAUGPT_YOUTUBE_PAGE_SIZE", "10")),
        },
        project_id=project_id,
        collection_id=collection_id,
        arena=str(row.get("arena") or ""),
        run_id=run_id,
    )
    result = runner.run("youtube", context)
    return {
        "plugin": "youtube",
        "source": str(row.get("name") or ""),
        "records_seen": result.records_seen,
        "records_written": result.records_written,
        "duplicates_skipped": result.duplicates_skipped,
        "warnings": result.warnings,
    }


def collect_manifest(
    manifest_path: Path,
    *,
    project_id: str = "brazil26",
    collection_id: str = "brazil26",
    machine: str = "laptop",
    run_id: str = "",
) -> dict[str, Any]:
    if project_id != "brazil26" or collection_id != "brazil26":
        raise ValueError("Brazil26 collector requires project_id=collection_id=brazil26")

    manifest = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    store = build_record_store(Settings())
    plugins = default_registry()
    runs: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []

    for row in manifest.get("youtube_source", []):
        urls = row.get("video_urls") or []
        if urls:
            runs.append(
                _run_youtube(
                    plugins,
                    store,
                    row,
                    project_id=project_id,
                    collection_id=collection_id,
                    machine=machine,
                    run_id=run_id,
                )
            )
        else:
            skipped.append(
                {
                    "source": str(row.get("name") or ""),
                    "reason": "no explicit video_urls; channel expansion is never guessed",
                }
            )

    return {
        "project_id": project_id,
        "collection_id": collection_id,
        "machine": machine,
        "runs": runs,
        "skipped": skipped,
        "notes": [
            "RSS is executed by the same shell wrapper before this plugin pass.",
            "Browser/X/Instagram/TikTok capture remains manual and loopback-only.",
            "YouTube channel homepages are not expanded into invented video targets.",
            "Political identities and source-family labels remain sampling provenance only.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="brazil26-localhost-collect")
    parser.add_argument("--source-manifest", required=True)
    parser.add_argument("--project-id", default="brazil26")
    parser.add_argument("--collection-id", default="brazil26")
    parser.add_argument("--machine", default=os.getenv("LACLAUGPT_MACHINE", "laptop"))
    parser.add_argument("--run-id", default=os.getenv("LACLAUGPT_RUN_ID", ""))
    args = parser.parse_args(argv)
    result = collect_manifest(
        Path(args.source_manifest),
        project_id=args.project_id,
        collection_id=args.collection_id,
        machine=args.machine,
        run_id=args.run_id,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
