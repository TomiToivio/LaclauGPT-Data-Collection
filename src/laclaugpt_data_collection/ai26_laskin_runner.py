"""Bounded Phase 1 AI26 non-browser worker for Laskin.

The worker consumes the shared study/source manifest, never starts browser/X
collection, and writes every collected record through the canonical distributed
MongoDB/Redis/S3 plane. Machine identity is provenance only.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import time
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

from .collectors.arxiv import ArxivCollector
from .collectors.bluesky import BlueskyCollector
from .collectors.rss import RSSCollector
from .collectors.youtube import YouTubeCollector
from .config import Settings
from .distributed_capture import DistributedCaptureSink
from .models import CollectionProvenance, NormalizedRecord
from .plugins import RetryPolicy
from .realtime import RealtimePolicy, parse_source_time
from .server_runner import run_phase1_rss
from .web_fetch import fetch_web_child

_BROWSER_ONLY_TABLES = {"x_account", "browser_source", "instagram_account", "tiktok_account"}
_WEB_SOURCE_FEED_FALLBACKS = {
    "https://openai.com/news": "https://openai.com/news/rss.xml",
}

_NON_BROWSER_TABLES = (
    "web_source",
    "bluesky_account",
    "mastodon_account",
    "youtube_source",
    "scholarly_query",
)

# Optional dependency contract for configured source families. Keep this aligned with
# pyproject.toml's phase1-non-browser aggregate extra. Kinds absent here use core deps.
_OPTIONAL_DEPENDENCY_CONTRACT: dict[str, tuple[str, tuple[str, ...]]] = {
    "mastodon_account": ("mastodon", ("mastodon",)),
    "youtube_source": ("youtube", ("yt_dlp",)),
    "scholarly_query": ("documents", ("arxiv",)),
}


class SourceJobError(RuntimeError):
    """Machine-readable failure of a configured source, not an empty result."""

    def __init__(self, reason: str, *, status_code: int | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status_code = status_code


def preflight_optional_dependencies(jobs: list[dict[str, Any]]) -> list[str]:
    """Return loud setup errors for configured job kinds missing optional packages."""
    configured: dict[str, list[str]] = {}
    for row in jobs:
        kind = str(row.get("kind") or "")
        if kind in _OPTIONAL_DEPENDENCY_CONTRACT:
            configured.setdefault(kind, []).append(str(row.get("name") or "unnamed"))

    errors: list[str] = []
    for kind, names in sorted(configured.items()):
        extra, modules = _OPTIONAL_DEPENDENCY_CONTRACT[kind]
        missing = [module for module in modules if importlib.util.find_spec(module) is None]
        if missing:
            errors.append(
                f"missing optional extra '{extra}' for job kind '{kind}' "
                f"(configured jobs: {', '.join(names)}; missing modules: {', '.join(missing)})"
            )
    return errors


def load_collector_retry_policy(study_config: str | Path) -> RetryPolicy:
    """Read ``collector_defaults.retry`` from the study config (#212).

    The AI26 Laskin runner drives collectors directly rather than through
    ``PluginRunner``, so it must honour the same declared retry budget itself.
    Missing or malformed values fall back to the conservative defaults rather
    than failing a whole tick.
    """
    defaults = RetryPolicy()
    try:
        data = yaml.safe_load(Path(study_config).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return defaults
    if not isinstance(data, dict):
        return defaults
    retry = (data.get("collector_defaults") or {}).get("retry") or {}
    if not isinstance(retry, dict):
        return defaults

    def _positive(value: Any, fallback: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return fallback
        return parsed if parsed >= 1 else fallback

    def _non_negative(value: Any, fallback: float) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return fallback
        return parsed if parsed >= 0 else fallback

    return RetryPolicy(
        max_attempts=_positive(retry.get("max_attempts"), defaults.max_attempts),
        base_delay_seconds=_non_negative(
            retry.get("initial_backoff_seconds"), defaults.base_delay_seconds
        ),
        max_delay_seconds=_non_negative(
            retry.get("max_backoff_seconds"), defaults.max_delay_seconds
        ),
    )


def _retryable_http_status(exc: BaseException) -> int | None:
    """Return the HTTP status of a retryable arxiv/requests error, else None.

    ``requests`` is an optional dependency here, so its presence is not assumed:
    the arxiv ``HTTPError`` carries a plain ``status`` attribute and is handled
    without it.
    """
    try:
        import requests
    except ImportError:  # requests ships with the optional 'documents' extra
        requests = None
    if requests is not None and isinstance(exc, requests.exceptions.HTTPError):
        status = getattr(getattr(exc, "response", None), "status_code", None)
        return int(status) if status else None
    status = getattr(exc, "status", None)
    if isinstance(status, int) and 400 <= status < 600:
        return status
    return None


def _call_with_retry(
    func: Callable[[], Any], *, policy: RetryPolicy, is_retryable: Callable[[BaseException], bool]
) -> Any:
    """Call ``func`` with a bounded backoff, re-raising the last error when exhausted.

    Owned here at the orchestration boundary, exactly like ``PluginRunner`` does
    for plugin-driven collectors, so the AI26 Laskin path honours the study
    config's declared retry budget instead of silently costing a tick (#212).
    """
    attempts = max(1, policy.max_attempts)
    for attempt in range(1, attempts + 1):
        try:
            return func()
        except Exception as exc:  # noqa: BLE001 - re-raised unless retryable and budget remains
            if attempt >= attempts or not is_retryable(exc):
                raise
            time.sleep(policy.delay_for(attempt))
    raise AssertionError("unreachable")  # pragma: no cover


def load_non_browser_jobs(path: str | Path) -> list[dict[str, Any]]:
    data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    jobs: list[dict[str, Any]] = []
    for table in _NON_BROWSER_TABLES:
        rows = data.get(table) or []
        if not isinstance(rows, list):
            raise ValueError(f"source manifest {table!r} must be an array of tables")
        for row in rows:
            if not isinstance(row, dict) or row.get("enabled", row.get("active", True)) is False:
                continue
            jobs.append({"kind": table, **row})
    return jobs


def select_job_window(
    jobs: list[dict[str, Any]], *, max_jobs: int, rotation: int = 0
) -> list[dict[str, Any]]:
    if max_jobs < 1:
        raise ValueError("max_jobs must be at least 1")
    if not jobs:
        return []
    rank = {"P1": 1, "P2": 2, "P3": 3}
    ordered = sorted(jobs, key=lambda row: rank.get(str(row.get("priority", "P2")).upper(), 2))
    shift = rotation % len(ordered)
    return (ordered[shift:] + ordered[:shift])[:max_jobs]


def _stamp(record: NormalizedRecord, row: dict[str, Any], *, collection_id: str, worker_id: str):
    record.source.raw_metadata["collection_id"] = collection_id
    record.source.raw_metadata["source_name"] = str(row.get("name") or "")
    record.source.raw_metadata["source_family"] = str(row.get("source_family") or "")
    record.source.raw_metadata["sampling_priority"] = str(row.get("priority") or "")
    arena = str(row.get("arena") or "")
    if arena:
        record.source.raw_metadata["arena"] = arena
    if record.provenance:
        record.provenance[-1].metadata.update(
            {
                "collection_id": collection_id,
                "worker_id": worker_id,
                "source_name": str(row.get("name") or ""),
            }
        )
        if arena:
            record.provenance[-1].metadata["arena"] = arena
    record.refresh_human_readable()
    return record


def _records_for_job(
    row: dict[str, Any],
    *,
    collection_id: str,
    worker_id: str,
    per_source_limit: int,
    retry_policy: RetryPolicy | None = None,
) -> tuple[list[NormalizedRecord], list[str]]:
    kind = str(row["kind"])
    if kind == "bluesky_account":
        handle = str(row.get("handle") or "").strip()
        if not handle:
            raise SourceJobError("missing_handle")
        result = BlueskyCollector(actor=handle, max_results=per_source_limit).collect()
        return [_stamp(r, row, collection_id=collection_id, worker_id=worker_id) for r in result.records], list(result.warnings)

    if kind == "scholarly_query":
        services = {str(v).lower() for v in row.get("services") or []}
        if "arxiv" not in services:
            raise SourceJobError("unsupported_scholarly_backend")
        query = str(row.get("query") or "").strip()
        if not query:
            raise SourceJobError("missing_query")
        # The arXiv endpoint rate-limits (HTTP 429) and occasionally 5xx's. The
        # library retries quickly and then gives up; without a bounded, backed-off
        # retry at this boundary a single transient status silently costs a tick's
        # scholarly records (#212).
        result = _call_with_retry(
            lambda: ArxivCollector(query, max_results=per_source_limit).collect(),
            policy=retry_policy or RetryPolicy(),
            is_retryable=lambda exc: _retryable_http_status(exc) in (429, 500, 502, 503, 504),
        )
        return [_stamp(r, row, collection_id=collection_id, worker_id=worker_id) for r in result.records], list(result.warnings)

    if kind == "youtube_source":
        urls = row.get("video_urls") or ([] if not row.get("video_url") else [row["video_url"]])
        if not urls:
            raise SourceJobError("missing_video_urls")
        result = YouTubeCollector([str(v) for v in urls], page_size=per_source_limit).collect()
        return [_stamp(r, row, collection_id=collection_id, worker_id=worker_id) for r in result.records], list(result.warnings)

    if kind == "web_source":
        url = str(row.get("homepage") or row.get("url") or "").strip()
        if not url:
            raise SourceJobError("missing_web_url")
        fallback_feed = _WEB_SOURCE_FEED_FALLBACKS.get(url.rstrip("/"))
        if fallback_feed:
            result = RSSCollector(
                [fallback_feed], max_items_per_feed=per_source_limit
            ).collect()
            return [
                _stamp(r, row, collection_id=collection_id, worker_id=worker_id)
                for r in result.records
            ], list(result.warnings)
        parent = NormalizedRecord(
            document_id=url,
            platform="web",
            source_url=url,
            text="",
            raw_payload={},
            collection_provenance=CollectionProvenance(module="ai26-laskin-web-seed"),
        )
        outcome = fetch_web_child(
            url,
            parent,
            collection_id=collection_id,
            arena=str(row.get("arena") or ""),
        )
        if outcome.record is None:
            raise SourceJobError("web_fetch_failed", status_code=outcome.status_code)
        return [_stamp(outcome.record, row, collection_id=collection_id, worker_id=worker_id)], []

    if kind == "mastodon_account":
        # The checked-in manifest stores actor acct values, while the current
        # generic Mastodon collector is timeline/hashtag based. Do not silently
        # substitute a public timeline for the named actor.
        raise SourceJobError("unsupported_mastodon_actor")

    raise SourceJobError("unsupported_source_kind")


def run_phase1_laskin(
    settings: Settings,
    *,
    study_config: str | Path,
    source_manifest: str | Path,
    collection_id: str | None = None,
    worker_id: str = "laskin-cron",
    max_feeds: int = 8,
    max_jobs: int = 6,
    per_source_limit: int = 5,
    limit: int = 40,
    rotation: int | None = None,
) -> dict[str, Any]:
    routed = collection_id or settings.project_id
    if routed != settings.project_id:
        raise ValueError("Laskin must use the configured project_id as collection_id")
    if rotation is None:
        rotation = int(time.time() // 3600)

    all_jobs = load_non_browser_jobs(source_manifest)
    setup_errors = preflight_optional_dependencies(all_jobs)
    if setup_errors:
        return {
            "status": "setup_error",
            "project_id": settings.project_id,
            "collection_id": routed,
            "worker_id": worker_id,
            "browser_sources_started": 0,
            "rss_records_synced": 0,
            "non_browser_jobs_considered": 0,
            "non_browser_records_collected": 0,
            "non_browser_records_synced": 0,
            "records_synced": 0,
            "skipped_before_publication_floor": 0,
            "warnings": [],
            "errors": setup_errors,
            "setup_errors": setup_errors,
            "notification_errors": [],
            "source_outcomes": [],
        }

    rss = run_phase1_rss(
        settings,
        study_config=study_config,
        source_manifest=source_manifest,
        collection_id=routed,
        worker_id=worker_id,
        max_feeds=max_feeds,
        per_feed_limit=per_source_limit,
        limit=limit,
        rotation=rotation * max_feeds,
    )
    remaining = max(limit - int(rss.get("records_synced", 0)), 0)
    sink = DistributedCaptureSink(settings)
    sink.assert_private_config(study_config)
    retry_policy = load_collector_retry_policy(study_config)
    policy = RealtimePolicy.ai26()
    jobs = select_job_window(all_jobs, max_jobs=max_jobs, rotation=rotation * max_jobs)
    synced = 0
    collected = 0
    skipped_before_floor = 0
    warnings = list(rss.get("warnings") or [])
    errors = list(rss.get("errors") or [])
    source_outcomes: list[dict[str, Any]] = []

    for row in jobs:
        outcome: dict[str, Any] = {
            "kind": str(row.get("kind") or ""),
            "name": str(row.get("name") or "unnamed"),
            "priority": str(row.get("priority") or "P2"),
            "status": "deferred",
            "reason": "tick_record_limit",
            "records_collected": 0,
            "records_synced": 0,
            "skipped_before_publication_floor": 0,
        }
        source_outcomes.append(outcome)
        if synced >= remaining:
            continue
        try:
            records, source_warnings = _records_for_job(
                row,
                collection_id=routed,
                worker_id=worker_id,
                per_source_limit=per_source_limit,
                retry_policy=retry_policy,
            )
            warnings.extend(source_warnings)
            collected += len(records)
            outcome.update(
                status="warning" if source_warnings else "ok",
                reason="collector_warnings" if source_warnings else "",
                records_collected=len(records),
            )
            for record in records:
                published = parse_source_time(record.source.created_at)
                if policy.publication_date_floor and published and published < policy.publication_date_floor:
                    skipped_before_floor += 1
                    outcome["skipped_before_publication_floor"] += 1
                    continue
                if synced >= remaining:
                    break
                if record.provenance:
                    provenance = record.provenance[-1]
                    provenance.metadata["caller"] = settings.caller
                    provenance.metadata["execution"] = settings.execution
                    if settings.run_id and not provenance.run_id:
                        provenance.run_id = settings.run_id
                payload = record.model_dump(mode="json")
                payload["collection_id"] = routed
                arena = str(record.source.raw_metadata.get("arena") or "")
                if arena:
                    payload["arena"] = arena
                sink.ingest(payload)
                synced += 1
                outcome["records_synced"] += 1
        except SourceJobError as exc:
            outcome.update(
                status="blocked" if exc.status_code in (401, 403) else "error",
                reason=exc.reason,
                http_status=exc.status_code,
            )
            errors.append(f"{row.get('kind')}:{row.get('name','unnamed')}: {exc.reason}")
        except Exception as exc:  # noqa: BLE001
            outcome.update(status="error", reason="collection_or_ingest_failed")
            errors.append(f"{row.get('kind')}:{row.get('name','unnamed')}: {str(exc)[:180]}")

    return {
        "status": "ok" if not errors else "partial",
        "project_id": settings.project_id,
        "collection_id": routed,
        "worker_id": worker_id,
        "browser_sources_started": 0,
        "rss_records_synced": int(rss.get("records_synced", 0)),
        "non_browser_jobs_considered": len(jobs),
        "non_browser_records_collected": collected,
        "non_browser_records_synced": synced,
        "records_synced": int(rss.get("records_synced", 0)) + synced,
        "skipped_before_publication_floor": int(rss.get("skipped_before_publication_floor", 0)) + skipped_before_floor,
        "warnings": warnings,
        "errors": errors,
        "source_outcomes": source_outcomes,
        "notification_errors": list(rss.get("notification_errors") or []) + list(sink.notification_errors),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="laclaugpt-ai26-laskin")
    parser.add_argument("--study-config", required=True)
    parser.add_argument("--source-manifest", required=True)
    parser.add_argument("--collection-id", default=None)
    parser.add_argument("--worker-id", default="laskin-cron")
    parser.add_argument("--max-feeds", type=int, default=8)
    parser.add_argument("--max-jobs", type=int, default=6)
    parser.add_argument("--per-source-limit", type=int, default=5)
    parser.add_argument("--limit", type=int, default=40)
    args = parser.parse_args(argv)
    result = run_phase1_laskin(
        Settings(),
        study_config=args.study_config,
        source_manifest=args.source_manifest,
        collection_id=args.collection_id,
        worker_id=args.worker_id,
        max_feeds=args.max_feeds,
        max_jobs=args.max_jobs,
        per_source_limit=args.per_source_limit,
        limit=args.limit,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if not result["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
