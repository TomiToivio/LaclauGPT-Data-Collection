"""Bounded Phase 1 AI26 non-browser worker for Laskin.

The worker consumes the shared study/source manifest, never starts browser/X
collection, and writes every collected record through the canonical distributed
MongoDB/Redis/S3 plane. Machine identity is provenance only.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import time
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

from .collectors.arxiv import ArxivCollector
from .collectors.bluesky import BlueskyCollector
from .collectors.mastodon import MastodonCollectionError, MastodonCollector
from .collectors.rss import RSSCollector
from .collectors.youtube import YouTubeCollector
from .config import Settings
from .distributed_capture import DistributedCaptureSink, HollowRecordError
from .distributed_jobs import LASKIN_CAPABILITIES as _QUEUE_LASKIN_CAPABILITIES
from .language import unlabelled_language_warning
from .models import CanonicalRecord, CollectionProvenance, NormalizedRecord
from .plugins import RetryPolicy
from .realtime import RealtimePolicy, parse_source_time, unparsed_source_time_warning
from .server_runner import run_phase1_rss
from .web_discovery import discover_article_urls, discover_feed_urls
from .web_fetch import fetch_html_page, fetch_web_child

_BROWSER_ONLY_TABLES = {"x_account", "browser_source", "instagram_account", "tiktok_account"}
_WEB_SOURCE_FEED_FALLBACKS = {
    "https://openai.com/news": "https://openai.com/news/rss.xml",
    # Microsoft AI blog (#251): the blog page has no scrapeable feed discovery on the
    # browser-free stage, so the verified feed is collected directly. Keyed without the
    # trailing slash because the lookup below rstrips it.
    "https://www.microsoft.com/en-us/ai/blog": "https://www.microsoft.com/en-us/ai/blog/feed/",
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


def _stamp(record: CanonicalRecord, row: dict[str, Any], *, collection_id: str, worker_id: str):
    record.source.raw_metadata["collection_id"] = collection_id
    record.source.raw_metadata["source_name"] = str(row.get("name") or "")
    record.source.raw_metadata["source_family"] = str(row.get("source_family") or "")
    record.source.raw_metadata["sampling_priority"] = str(row.get("priority") or "")
    arena = str(row.get("arena") or "")
    if arena:
        record.source.raw_metadata["arena"] = arena
    # #296: a row that declares it links at an aggregator says so once, here.
    from .source_identity import apply_source_identity

    record.source.raw_metadata.update(apply_source_identity(record, row))
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
    # #294: a row-level `language = "fi"` fills an empty record language. It is
    # recorded as a DECLARATION (language_declared_by=manifest_row), never mixed
    # with an observed or detected tag, so the strata stay separable in analysis.
    from .language import apply_declared_language

    language_method = apply_declared_language(record, str(row.get("language") or ""))
    if language_method and record.provenance:
        record.provenance[-1].metadata["language_method"] = language_method
        record.provenance[-1].metadata["language_declared_by"] = "manifest_row"
    # Some institutional Bluesky posts have no declared language (#294).
    # Infer only from substantive text, preserving unknowns and provenance.
    if not record.source.language:
        from .language import resolve_language

        candidate = record.content.text or ""
        detected, method = resolve_language(candidate)
        if detected:
            record.source.language = detected
            record.source.raw_metadata["language_method"] = method
    record.refresh_human_readable()
    return record


def _records_for_job(
    row: dict[str, Any],
    *,
    collection_id: str,
    worker_id: str,
    per_source_limit: int,
    retry_policy: RetryPolicy | None = None,
) -> tuple[list[CanonicalRecord], list[str]]:
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

        # #321: a web_source is a homepage, so the stage has to discover what it
        # publishes before it can store anything the handoff will accept. Feeds first
        # (they carry dates and need no per-site knowledge, which is why the hardcoded
        # fallback map above was the wrong shape), then article links, whose pages
        # carry article:published_time for the existing fetcher to read. Only when
        # neither route yields a dated document does the old single-snapshot behaviour
        # remain, and that snapshot is still excluded downstream rather than guessed at.
        page = fetch_html_page(url)
        if page is not None:
            final_url, html = page
            feed_urls = discover_feed_urls(html, final_url)[:3]
            if feed_urls:
                result = RSSCollector(
                    feed_urls, max_items_per_feed=per_source_limit
                ).collect()
                dated = [
                    r for r in result.records if getattr(r.source, "created_at", None)
                ]
                if dated:
                    return [
                        _stamp(r, row, collection_id=collection_id, worker_id=worker_id)
                        for r in dated
                    ], list(result.warnings)
            children: list[CanonicalRecord] = []
            for candidate in discover_article_urls(
                html, final_url, limit=per_source_limit
            ):
                child = fetch_web_child(
                    candidate,
                    parent,
                    collection_id=collection_id,
                    arena=str(row.get("arena") or ""),
                )
                if child.record is not None and getattr(child.record.source, "created_at", None):
                    children.append(child.record)
            if children:
                return [
                    _stamp(r, row, collection_id=collection_id, worker_id=worker_id)
                    for r in children
                ], []

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
        acct = str(row.get("acct") or "").strip().removeprefix("@")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+@[A-Za-z0-9.-]+(?::[0-9]+)?", acct):
            raise SourceJobError("invalid_mastodon_acct")
        _, host = acct.split("@", 1)
        result = _call_with_retry(
            lambda: MastodonCollector(
                f"https://{host}", acct=acct, limit=min(per_source_limit, 40)
            ).collect(),
            policy=retry_policy or RetryPolicy(),
            is_retryable=lambda exc: isinstance(exc, MastodonCollectionError) and exc.retryable,
        )
        return [
            _stamp(r, row, collection_id=collection_id, worker_id=worker_id)
            for r in result.records
        ], list(result.warnings)

    raise SourceJobError("unsupported_source_kind")


def _declared_budgets_bind(study_config: str | Path) -> bool:
    """Whether the study config declares its source caps as binding (#239.2).

    A `source_budgets` block whose caps exist but bind nothing is the least
    desirable state the issue names. The study declares the binding explicitly:

        source_budgets:
          enforce: true

    Absent or false keeps the previous opt-in behaviour, so an existing config is
    never silently changed into a capped run.
    """
    try:
        import yaml

        data = yaml.safe_load(Path(study_config).read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001 - a missing config must not enable a cap
        return False
    budgets = data.get("source_budgets")
    if not isinstance(budgets, dict):
        return False
    return budgets.get("enforce") is True


def _rss_window(
    max_feeds: int, rss_limit: int, per_source_limit: int = 5
) -> tuple[int, int]:
    """How many feeds to poll and how deep, so the window fits the allocation (#293).

    The RSS stage fetched a window it could not store: with 8 feeds at 5 candidates against a
    20-record allocation, half of every cycle's fetch was discarded and a feed in the tail of the
    window collected nothing for hours. The budget has to size the window, not the other way
    round, so ``feeds * depth <= rss_limit`` holds by construction.

    The feed count shrinks to fit the declared depth; the depth is NOT shrunk to fit the feed
    count. Depth reduction looks free -- 8 feeds at 2 candidates fills 16 of 20 -- but it changes
    *which* records a cycle can store: only a feed's two newest items are ever fetched, so a feed
    publishing three items between two cycles silently loses the middle one forever, and the
    stored set stops being the prefix of an unbounded fetch that #301 pinned. Four feeds at the
    declared depth of five store the same 20 records the budget always stored, and the rotation
    gives the other 28 feeds their turn within a bounded number of cycles.

    Returns ``(feeds, depth)``.
    """
    if rss_limit <= 0:
        return (0, 0)
    depth = max(1, min(per_source_limit, rss_limit))
    feeds = min(max(1, max_feeds), max(1, rss_limit // depth))
    return (feeds, depth)




# -- distributed queue (#378) -------------------------------------------------------------
#
# The lease queue and its capability rule already existed and were proven against the
# shared MongoDB; the live cron did not consume them, so every host still ran its own
# copy of the manifest. This is the missing half: the queue decides *which* job this
# tick runs, the manifest still decides *what jobs exist*.

QUEUE_COLLECTION = "ai26_jobs"
# Laskin never runs Firefox or a browser session, so it declares only this capability.
# The enforcement itself lives in the claim query (distributed_jobs.capability_filter),
# not in this flag: a worker without "browser" cannot be handed a browser job at all.
# Re-exported from the queue module rather than redefined: a second spelling of the
# capability set is how a worker ends up silently asking for the wrong permissions.
LASKIN_CAPABILITIES = _QUEUE_LASKIN_CAPABILITIES
_PRIORITY_TO_INT = {"P1": 1, "P2": 2, "P3": 3}


def queue_rows_from_manifest(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map manifest rows to queue jobs with a stable, idempotent job id.

    ``kind:name`` rather than a random id is what makes re-enqueueing the same
    manifest a no-op instead of a second copy of the work.
    """
    rows: list[dict[str, Any]] = []
    for row in jobs:
        kind = str(row.get("kind") or "")
        name = str(row.get("name") or "")
        if not kind or not name:
            continue
        raw_priority = row.get("priority", "P2")
        if isinstance(raw_priority, int):
            priority = raw_priority
        else:
            priority = _PRIORITY_TO_INT.get(str(raw_priority).upper(), 2)
        rows.append({"job_id": f"{kind}:{name}", "kind": kind, "name": name,
                     "priority": priority, "payload": dict(row)})
    return rows


def queue_store(settings: Settings, collection_name: str = QUEUE_COLLECTION) -> Any:
    """Lease store over the shared MongoDB, or None when no URI is configured.

    Returning None rather than raising keeps the wrapper's manifest path working on a
    host that has no database, which is the fallback the issue asks for.
    """
    uri = getattr(settings, "mongodb_uri", "") or ""
    if not uri:
        return None
    from pymongo import MongoClient

    from .distributed_jobs import JobLeaseStore

    client = MongoClient(uri, serverSelectionTimeoutMS=settings.mongodb_connect_timeout_ms)
    store = JobLeaseStore(client[settings.mongodb_database][collection_name])
    store.ensure_indexes()
    return store


def claimed_jobs_for_run(
    leases: list[dict[str, Any]], rows: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[str]]:
    """Pair leases back to manifest rows, keeping only jobs this manifest describes.

    A lease whose job is no longer in the manifest is returned in ``orphaned`` so the
    caller can release it rather than leave it RUNNING until the lease expires.
    """
    by_id = {row["job_id"]: row for row in rows}
    jobs: list[dict[str, Any]] = []
    orphaned: list[str] = []
    for lease in leases:
        job_id = str(lease.get("_id") or "")
        row = by_id.get(job_id)
        if row is None:
            orphaned.append(job_id)
            continue
        jobs.append(dict(row["payload"], job_id=job_id, kind=row["kind"], name=row["name"]))
    return jobs, orphaned


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
    tracked_plan: str | Path | None = None,
    enforce_source_budgets: bool | None = None,
    claimed_jobs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    routed = collection_id or settings.project_id
    if routed != settings.project_id:
        raise ValueError("Laskin must use the configured project_id as collection_id")
    if rotation is None:
        rotation = int(time.time() // 3600)

    all_jobs = load_non_browser_jobs(source_manifest)
    if claimed_jobs is not None:
        # The queue, not this process, decides what runs this tick. Without this,
        # every host would run its own copy of the manifest and the lease would be
        # decoration (#378).
        all_jobs = claimed_jobs
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
            "records_new": 0,
            "records_updated": 0,
            "skipped_before_publication_floor": 0,
            "warnings": [],
            "errors": setup_errors,
            "setup_errors": setup_errors,
            "notification_errors": [],
            "source_outcomes": [],
            "manifest_drift": None,
            "source_budget": None,
            "deferred_by_source_budget": 0,
        }

    # Reserve a bounded share for non-browser jobs before RSS re-syncs can exhaust
    # the common write limit. This changes allocation, not the total tick cap.
    # No reservation is needed when the manifest has no eligible jobs.
    non_browser_reserve = min(limit // 2, max_jobs * per_source_limit) if all_jobs else 0
    rss_limit = limit - non_browser_reserve
    # Never fetch more feed candidates than can be persisted in this tick (#293).
    # Preserve the total tick cap and the non-browser reservation.
    rss_feeds, rss_feed_depth = _rss_window(max_feeds, rss_limit, per_source_limit)
    rss = run_phase1_rss(
        settings,
        study_config=study_config,
        source_manifest=source_manifest,
        collection_id=routed,
        worker_id=worker_id,
        max_feeds=rss_feeds,
        per_feed_limit=rss_feed_depth,
        limit=rss_limit,
        rotation=rotation * rss_feeds,
    )
    remaining = max(limit - int(rss.get("records_synced", 0)), 0)
    created = int(rss.get("records_new", 0))
    deferred_by_budget = 0
    sink = DistributedCaptureSink(settings)
    sink.assert_private_config(study_config)
    retry_policy = load_collector_retry_policy(study_config)

    # Issue #215: the study DECLARES per-source daily caps in `source_budgets`, but
    # nothing enforced them, so a prolific source's records accumulated unchecked.
    # Opt-in, because enabling a cap changes what the corpus contains -- a sampling
    # decision. The day's count comes from the store, since one hourly cycle is one
    # process and a memory counter would reset every tick.
    # Issue #239.2: the study DECLARES the caps; a declaration in the audited
    # config should bind the pipeline it governs, rather than depending on a
    # wrapper flag nobody passes. `enforce_source_budgets` stays as an explicit
    # override: True forces the declared caps on, False forces them off (for a
    # deliberate unbounded run), None -- the default -- follows the study config.
    if enforce_source_budgets is None:
        enforce_source_budgets = _declared_budgets_bind(study_config)
    budget = None
    if enforce_source_budgets:
        from .source_budget import SourceDailyBudget, load_source_caps, utc_day

        identities = [str(row.get("name") or "") for row in all_jobs if row.get("name")]
        # Map each configured source to its platform, so only account-shaped
        # sources receive a per-source cap.
        source_platform = {
            str(row.get("name")): str(row.get("kind") or "").replace("_account", "")
            for row in all_jobs
            if row.get("name")
        }
        caps = load_source_caps(study_config, identities, platforms=source_platform)
        if caps:
            since = f"{utc_day()}T00:00:00+00:00"
            budget = SourceDailyBudget(
                caps=caps,
                count_today=lambda name, _day: sink.records.count_by_source_since(
                    name, since_iso=since, collection_id=routed
                ),
            )
    policy = RealtimePolicy.ai26()
    jobs = (
        claimed_jobs
        if claimed_jobs is not None
        else select_job_window(all_jobs, max_jobs=max_jobs, rotation=rotation * max_jobs)
    )
    synced = 0
    collected = 0
    skipped_before_floor = 0
    warnings = list(rss.get("warnings") or [])
    errors = list(rss.get("errors") or [])
    source_outcomes: list[dict[str, Any]] = []
    deferred_by_tick_limit = 0

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
            deferred_by_tick_limit += 1
            continue
        try:
            records, source_warnings = _records_for_job(
                row,
                collection_id=routed,
                worker_id=worker_id,
                per_source_limit=per_source_limit,
                retry_policy=retry_policy,
            )
            # #295: warn by source when publication timestamps cannot be parsed.
            unparsed_time_warning = unparsed_source_time_warning(records)
            if unparsed_time_warning:
                source_warnings = [*source_warnings, unparsed_time_warning]
            warnings.extend(source_warnings)
            # #294: a missing language tag is a metadata-quality report, not a
            # source-health failure, so it goes into the cycle warnings without
            # changing this job's outcome status.
            language_warning = unlabelled_language_warning(records)
            if language_warning:
                warnings.append(language_warning)
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
                if budget is not None and not budget.admit(payload):
                    deferred_by_budget += 1
                    continue
                _, record_created = sink.ingest_with_status(payload)
                synced += 1
                outcome["records_synced"] += 1
                if record_created:
                    created += 1
        except SourceJobError as exc:
            outcome.update(
                status="blocked" if exc.status_code in (401, 403) else "error",
                reason=exc.reason,
                http_status=exc.status_code,
            )
            errors.append(f"{row.get('kind')}:{row.get('name','unnamed')}: {exc.reason}")
        except HollowRecordError as exc:
            # #322: the sink refused a capture that would have carried no text, no raw
            # payload/ref and no media. Report the refusal against the configured source
            # and URL, so a hollow capture is a visible source error rather than a silent
            # skip -- and rather than a success it cannot back up.
            outcome.update(status="error", reason=exc.reason)
            errors.append(
                f"{row.get('kind')}:{row.get('name','unnamed')}: {exc.reason}: {exc.source_url}"
            )
        except Exception as exc:  # noqa: BLE001
            outcome.update(status="error", reason="collection_or_ingest_failed")
            errors.append(f"{row.get('kind')}:{row.get('name','unnamed')}: {str(exc)[:180]}")

    # Issue #206: make source-manifest drift visible every cycle. The deployed
    # manifest is gitignored runtime config; the audited plan lives in
    # configs/studies/. When the plan gains a source, nothing used to say the
    # running set was behind it. `tracked_plan` is opt-in so the runner never
    # guesses a repository path, and the comparison is read-only.
    manifest_drift: dict[str, Any] | None = None
    if tracked_plan is not None:
        try:
            from .manifest_drift import compare_manifests, drift_summary

            drift_report = compare_manifests(source_manifest, tracked_plan)
            manifest_drift = {
                "in_sync": drift_report["in_sync"],
                "summary": drift_summary(drift_report),
                "added": drift_report["added"],
                "removed": drift_report["removed"],
                "deployed_total": drift_report["deployed_total"],
                "tracked_total": drift_report["tracked_total"],
            }
        except Exception as exc:  # noqa: BLE001 - a report must not fail the cycle
            manifest_drift = {"in_sync": None, "error": str(exc)[:180]}

    tick_budget = {
        "limit": limit,
        "rss_allocation": rss_limit,
        "non_browser_reserved": non_browser_reserve,
        "rss_synced": int(rss.get("records_synced", 0)),
        "non_browser_synced": synced,
        "unused": max(limit - int(rss.get("records_synced", 0)) - synced, 0),
        "jobs_admitted": [o["name"] for o in source_outcomes if o["reason"] != "tick_record_limit"],
        "jobs_deferred": [o["name"] for o in source_outcomes if o["reason"] == "tick_record_limit"],
        "deferred_jobs_tick_limit": deferred_by_tick_limit,
        "rotation": rotation,
        # #293: what the RSS window actually was and which feeds it polled. The
        # rotation is a position in the priority-ordered manifest; the window is
        # `window_size` feeds and advances by the same amount each cycle, so a
        # full pass takes `cycles_per_pass` cycles. Logged so per-feed cadence is
        # verifiable from the cycle log instead of inferred from timestamps.
        "rss_feed_window": {
            "rotation": int(rss.get("feed_window_rotation", 0) or 0),
            "window_size": rss_feeds,
            "window": list(rss.get("feed_names") or []),
            "polled": list(rss.get("feeds_polled_names") or []),
            "feeds_in_manifest": int(rss.get("feeds_in_manifest", 0) or 0),
            "cycles_per_pass": (
                -(-int(rss.get("feeds_in_manifest", 0) or 0) // rss_feeds)
                if rss_feeds
                else 0
            ),
        },
        "source_budget_deferrals_are_separate": True,
    }
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
        "records_new": created,
        "records_updated": (int(rss.get("records_synced", 0)) + synced) - created,
        "skipped_before_publication_floor": int(rss.get("skipped_before_publication_floor", 0)) + skipped_before_floor,
        "warnings": warnings,
        "errors": errors,
        "source_outcomes": source_outcomes,
        "tick_budget": tick_budget,
        "deferred_by_tick_limit": deferred_by_tick_limit,
        "source_budget": (budget.summary() if budget is not None else None),
        "deferred_by_source_budget": deferred_by_budget,
        "manifest_drift": manifest_drift,
        "notification_errors": list(rss.get("notification_errors") or []) + list(sink.notification_errors),
    }


def run_queued_laskin_cycle(
    settings: Settings,
    *,
    store: Any,
    study_config: str | Path,
    source_manifest: str | Path,
    worker_id: str = "laskin-cron",
    max_jobs: int = 6,
    lease_seconds: int = 900,
    **kwargs: Any,
) -> dict[str, Any]:
    """One bounded cycle driven by the lease queue instead of the local manifest.

    Enqueue -> claim -> run exactly what was claimed -> complete or release. The
    manifest still defines *what jobs exist*; the queue decides *which of them this
    tick runs*, so two hosts cannot collect the same job.
    """
    rows = queue_rows_from_manifest(load_non_browser_jobs(source_manifest))
    enqueued = store.enqueue(rows)
    leases = store.claim(worker_id, LASKIN_CAPABILITIES, limit=max_jobs,
                         lease_seconds=lease_seconds)
    jobs, orphaned = claimed_jobs_for_run(leases, rows)
    for job_id in orphaned:
        store.release(job_id, worker_id, error="job_not_in_manifest")
    if not jobs:
        return {"status": "idle", "queue": {"enqueued": enqueued, "claimed": 0,
                                            "completed": 0, "released": 0,
                                            "orphaned_released": len(orphaned)}}
    result = run_phase1_laskin(
        settings, study_config=study_config, source_manifest=source_manifest,
        worker_id=worker_id, claimed_jobs=jobs, **kwargs,
    )
    by_key = {
        f"{o.get('kind')}:{o.get('name')}": o for o in (result.get("source_outcomes") or [])
    }
    completed = released = 0
    for lease in leases:
        job_id = str(lease.get("_id") or "")
        if job_id in orphaned:
            continue
        outcome = by_key.get(job_id) or {}
        state = str(outcome.get("status") or "")
        if state in ("ok", "warning"):
            store.complete(job_id, worker_id, outcome=state)
            completed += 1
        else:
            # Not done is not done: a deferred, blocked or failed job goes back to
            # the queue so another worker (or a later attempt) can take it. Attempts
            # are bounded in the store, so this cannot spin forever.
            store.release(job_id, worker_id,
                          error=str(outcome.get("reason") or state or "no_outcome"))
            released += 1
    result["queue"] = {"enqueued": enqueued, "claimed": len(jobs), "completed": completed,
                       "released": released, "orphaned_released": len(orphaned)}
    return result


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
    # Three-state deliberately: `store_true` would make an ABSENT flag pass
    # False and thereby force the caps OFF, silently overriding a study that
    # declares `source_budgets.enforce: true` (#239.2). Default None = follow the
    # study config; the explicit flag forces on, --no-... forces off.
    parser.add_argument(
        "--enforce-source-budgets",
        dest="enforce_source_budgets",
        action="store_true",
        default=None,
        help="force the study's declared per-source daily caps ON (#215); default follows the study config",
    )
    parser.add_argument(
        "--no-enforce-source-budgets",
        dest="enforce_source_budgets",
        action="store_false",
        help="force the declared caps OFF for a deliberate unbounded run",
    )
    parser.add_argument(
        "--queue",
        action="store_true",
        help="consume the shared lease queue instead of selecting jobs locally (#378)",
    )
    parser.add_argument(
        "--queue-collection",
        default=QUEUE_COLLECTION,
        help=f"queue collection name (default: {QUEUE_COLLECTION})",
    )
    parser.add_argument(
        "--tracked-plan",
        default=None,
        help="audited plan under configs/studies/; when set, report manifest drift",
    )
    args = parser.parse_args(argv)
    settings = Settings()
    common = {
        "study_config": args.study_config,
        "source_manifest": args.source_manifest,
        "worker_id": args.worker_id,
        "max_feeds": args.max_feeds,
        "max_jobs": args.max_jobs,
        "per_source_limit": args.per_source_limit,
        "limit": args.limit,
        "tracked_plan": args.tracked_plan,
        "enforce_source_budgets": args.enforce_source_budgets,
    }
    if getattr(args, "queue", False):
        store = queue_store(settings, args.queue_collection)
        if store is None:
            result = {
                "status": "setup_error",
                "errors": ["queue mode requested but no MongoDB URI is configured"],
                "source_outcomes": [],
                "queue": {"enqueued": 0, "claimed": 0, "completed": 0, "released": 0},
            }
        else:
            result = run_queued_laskin_cycle(settings, store=store, **common)
    else:
        result = run_phase1_laskin(
            settings, collection_id=args.collection_id, **common
        )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if not result["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
