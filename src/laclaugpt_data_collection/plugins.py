"""Versioned collection-plugin contract, registry and durable runner.

The plugin layer is intentionally small. Source adapters remain responsible for acquisition
and source-specific normalization; this module standardizes how they are described, invoked,
stamped with project provenance and handed to backend-neutral canonical storage.
"""
from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Protocol

from .models import CanonicalRecord, CollectionProvenance
from .storage.base import RecordStore

if TYPE_CHECKING:
    from .collectors.base import CollectionResult

PluginMode = Literal["polling", "streaming", "manual", "batch", "webhook"]
RecordNotifier = Callable[[CanonicalRecord], None]


class LegacyCollector(Protocol):
    """Minimal interface required to adapt an existing source collector."""

    def collect(self) -> CollectionResult: ...


CollectorFactory = Callable[["CollectionContext"], LegacyCollector]


@dataclass(frozen=True, slots=True)
class PluginSpec:
    """Public, versioned declaration of one collection source plugin."""

    plugin_id: str
    version: str
    source_type: str
    config_schema: Mapping[str, Any] = field(default_factory=dict)
    authentication: str = "none"
    modes: tuple[PluginMode, ...] = ("polling",)
    retry_policy: str = "bounded exponential backoff at orchestration boundary"
    canonical_identifier: str = "stable source URL or URI-like identifier"
    raw_payload_policy: str = "preserve inline payload or immutable raw reference"
    media_policy: str = "store references; download only when project configuration enables it"
    scheduling: str = "project/private configuration decides cadence"

    def __post_init__(self) -> None:
        if not self.plugin_id.strip():
            raise ValueError("plugin_id is required")
        if not self.version.strip():
            raise ValueError("plugin version is required")
        if not self.source_type.strip():
            raise ValueError("source_type is required")
        if not self.modes:
            raise ValueError("at least one collection mode is required")


@dataclass(slots=True)
class CollectionContext:
    """Runtime context supplied by orchestration, not embedded in source plugins."""

    config: Mapping[str, Any] = field(default_factory=dict)
    project_id: str = ""
    collection_id: str = "default"
    arena: str = ""
    run_id: str = ""
    cursor: str | None = None
    privacy: Mapping[str, Any] = field(default_factory=dict)

    def require(self, key: str) -> Any:
        value = self.config.get(key)
        if value in (None, "", [], {}):
            raise ValueError(f"missing required plugin configuration: {key}")
        return value


class CollectionPlugin(Protocol):
    """Common contract implemented by first-party and future external plugins."""

    spec: PluginSpec

    def collect(self, context: CollectionContext) -> CollectionResult: ...


class CollectorPluginAdapter:
    """Adapt an existing ``Collector.collect()`` implementation to the plugin contract."""

    def __init__(self, spec: PluginSpec, factory: CollectorFactory) -> None:
        self.spec = spec
        self._factory = factory

    def collect(self, context: CollectionContext) -> CollectionResult:
        collector = self._factory(context)
        result = collector.collect()
        for record in result.records:
            _stamp_record(record, spec=self.spec, context=context)
        return result


class PluginRegistry:
    """In-process registry with deterministic IDs and no import-time network activity."""

    def __init__(self) -> None:
        self._plugins: dict[str, CollectionPlugin] = {}

    def register(self, plugin: CollectionPlugin) -> None:
        plugin_id = plugin.spec.plugin_id
        if plugin_id in self._plugins:
            raise ValueError(f"collection plugin already registered: {plugin_id}")
        self._plugins[plugin_id] = plugin

    def get(self, plugin_id: str) -> CollectionPlugin:
        try:
            return self._plugins[plugin_id]
        except KeyError as exc:
            known = ", ".join(self.ids()) or "none"
            raise KeyError(f"unknown collection plugin {plugin_id!r}; known: {known}") from exc

    def ids(self) -> list[str]:
        return sorted(self._plugins)

    def specs(self) -> list[PluginSpec]:
        return [self._plugins[plugin_id].spec for plugin_id in self.ids()]


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Bounded retry policy owned by orchestration rather than source adapters."""

    max_attempts: int = 3
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 30.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.base_delay_seconds < 0:
            raise ValueError("base_delay_seconds must be non-negative")
        if self.max_delay_seconds < 0:
            raise ValueError("max_delay_seconds must be non-negative")

    def delay_for(self, attempt: int, *, retry_after: str | None = None) -> float:
        """Return capped exponential backoff while honoring numeric Retry-After."""
        delay = min(
            self.max_delay_seconds,
            self.base_delay_seconds * (2 ** max(0, attempt - 1)),
        )
        if retry_after:
            try:
                delay = max(delay, float(retry_after))
            except ValueError:
                pass
        return min(delay, self.max_delay_seconds)


class CollectionRunError(RuntimeError):
    """Terminal or exhausted collection attempt with retry state preserved."""

    def __init__(
        self,
        plugin_id: str,
        *,
        attempts: int,
        cause: Exception,
        retryable: bool,
        retry_after: str | None = None,
    ) -> None:
        super().__init__(f"collection plugin {plugin_id!r} failed after {attempts} attempt(s): {cause}")
        self.plugin_id = plugin_id
        self.attempts = attempts
        self.cause = cause
        self.retryable = retryable
        self.retry_after = retry_after


@dataclass(slots=True)
class PluginRunResult:
    plugin_id: str
    records_seen: int
    records_written: int
    duplicates_skipped: int
    attempts: int = 1
    next_cursor: str | None = None
    warnings: list[str] = field(default_factory=list)


class CollectionRunner:
    """Run one plugin and durably persist records before optional notification.

    ``RecordStore.contains`` plus canonical ``source_url`` identity makes repeated cron-style
    execution idempotent for logical records. A queue/Redis notifier is deliberately optional
    and runs only after the canonical record has been written to durable storage.
    """

    def __init__(
        self,
        registry: PluginRegistry,
        store: RecordStore,
        *,
        retry_policy: RetryPolicy | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.registry = registry
        self.store = store
        self.retry_policy = retry_policy or RetryPolicy()
        self.sleep = sleep

    def run(
        self,
        plugin_id: str,
        context: CollectionContext,
        *,
        notify: RecordNotifier | None = None,
    ) -> PluginRunResult:
        plugin = self.registry.get(plugin_id)
        attempts = 0
        while True:
            attempts += 1
            try:
                result = plugin.collect(context)
                break
            except Exception as exc:
                retryable = bool(getattr(exc, "retryable", False))
                retry_after_value = getattr(exc, "retry_after", None)
                retry_after = (
                    str(retry_after_value) if retry_after_value not in (None, "") else None
                )
                exhausted = attempts >= self.retry_policy.max_attempts
                if not retryable or exhausted:
                    raise CollectionRunError(
                        plugin_id,
                        attempts=attempts,
                        cause=exc,
                        retryable=retryable,
                        retry_after=retry_after,
                    ) from exc
                delay = self.retry_policy.delay_for(
                    attempts,
                    retry_after=retry_after,
                )
                self.sleep(delay)

        written = 0
        duplicates = 0
        for record in result.records:
            if self.store.contains(record.source_url):
                duplicates += 1
                continue
            self.store.upsert(record)
            written += 1
            if notify is not None:
                notify(record)
        return PluginRunResult(
            plugin_id=plugin_id,
            records_seen=len(result.records),
            records_written=written,
            duplicates_skipped=duplicates,
            attempts=attempts,
            next_cursor=result.next_cursor,
            warnings=list(result.warnings),
        )


def adapt_collector(spec: PluginSpec, factory: CollectorFactory) -> CollectionPlugin:
    """Public helper for wrapping existing or third-party collector implementations."""
    return CollectorPluginAdapter(spec, factory)


def default_registry() -> PluginRegistry:
    """Return the first incrementally migrated first-party plugins.

    RSS and Bluesky exercise both feed-style and API-style collection. Other existing collectors
    can migrate through the same adapter without changing their source-specific implementation.
    """
    from .collectors.arxiv import ArxivCollector
    from .collectors.bluesky import BlueskyCollector
    from .collectors.mastodon import MastodonCollector
    from .collectors.rss import RSSCollector

    registry = PluginRegistry()

    def rss_factory(context: CollectionContext) -> LegacyCollector:
        feed_urls = context.require("feed_urls")
        if not isinstance(feed_urls, list) or not all(isinstance(url, str) for url in feed_urls):
            raise ValueError("rss feed_urls must be a list of strings")
        max_items = int(context.config.get("max_items_per_feed", 100))
        return RSSCollector(feed_urls=feed_urls, max_items_per_feed=max_items)

    registry.register(
        adapt_collector(
            PluginSpec(
                plugin_id="rss",
                version="1.0.0",
                source_type="rss",
                config_schema={
                    "type": "object",
                    "required": ["feed_urls"],
                    "properties": {
                        "feed_urls": {"type": "array", "items": {"type": "string"}},
                        "max_items_per_feed": {"type": "integer", "minimum": 1},
                    },
                },
                modes=("polling", "batch"),
                authentication="none for public feeds; private feeds supplied at runtime",
            ),
            rss_factory,
        )
    )

    def bluesky_factory(context: CollectionContext) -> LegacyCollector:
        query = context.config.get("query")
        actor = context.config.get("actor")
        max_results = int(context.config.get("max_results", 100))
        token = context.config.get("access_token")
        return BlueskyCollector(
            query=str(query) if query else None,
            actor=str(actor) if actor else None,
            max_results=max_results,
            access_token=str(token) if token else None,
            cursor=context.cursor,
        )

    registry.register(
        adapt_collector(
            PluginSpec(
                plugin_id="bluesky",
                version="1.0.0",
                source_type="bluesky",
                config_schema={
                    "type": "object",
                    "oneOf": [{"required": ["query"]}, {"required": ["actor"]}],
                    "properties": {
                        "query": {"type": "string"},
                        "actor": {"type": "string"},
                        "max_results": {"type": "integer", "minimum": 1},
                    },
                },
                modes=("polling", "batch"),
                authentication="public XRPC by default; optional runtime access token",
            ),
            bluesky_factory,
        )
    )

    def mastodon_factory(context: CollectionContext) -> LegacyCollector:
        instance_url = str(context.require("instance_url"))
        hashtag = context.config.get("hashtag")
        limit = int(context.config.get("limit", 20))
        token = context.config.get("access_token")
        return MastodonCollector(
            instance_url=instance_url,
            hashtag=str(hashtag) if hashtag else None,
            limit=limit,
            access_token=str(token) if token else None,
            cursor=context.cursor,
        )

    def arxiv_factory(context: CollectionContext) -> LegacyCollector:
        query = str(context.require("query"))
        max_results = int(context.config.get("max_results", 10))
        categories_value = context.config.get("categories", [])
        if categories_value in (None, ""):
            categories: list[str] = []
        elif isinstance(categories_value, list) and all(
            isinstance(category, str) for category in categories_value
        ):
            categories = categories_value
        else:
            raise ValueError("arxiv categories must be a list of strings")
        return ArxivCollector(
            query=query,
            max_results=max_results,
            categories=categories,
            cursor=context.cursor,
        )

    registry.register(
        adapt_collector(
            PluginSpec(
                plugin_id="arxiv",
                version="1.0.0",
                source_type="scholarly_document",
                config_schema={
                    "type": "object",
                    "required": ["query"],
                    "properties": {
                        "query": {"type": "string"},
                        "max_results": {"type": "integer", "minimum": 1},
                        "categories": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                },
                modes=("polling", "batch"),
                authentication="none for public arXiv API",
                canonical_identifier="canonical https://arxiv.org/abs/<id> URL",
                raw_payload_policy=(
                    "preserve deterministic bibliographic metadata snapshot inline; "
                    "PDF remains a referenced source object unless separately downloaded"
                ),
                media_policy=(
                    "preserve arXiv PDF URL as a media reference with download_required metadata"
                ),
            ),
            arxiv_factory,
        )
    )

    registry.register(
        adapt_collector(
            PluginSpec(
                plugin_id="mastodon",
                version="1.0.0",
                source_type="mastodon",
                config_schema={
                    "type": "object",
                    "required": ["instance_url"],
                    "properties": {
                        "instance_url": {"type": "string"},
                        "hashtag": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1},
                    },
                },
                modes=("polling", "batch"),
                authentication="public timelines by default; optional runtime access token",
                canonical_identifier="Mastodon status URL",
                raw_payload_policy="preserve exact status JSON inline",
            ),
            mastodon_factory,
        )
    )
    return registry


def _stamp_record(
    record: CanonicalRecord,
    *,
    spec: PluginSpec,
    context: CollectionContext,
) -> None:
    """Attach plugin/project provenance without introducing a second record schema."""
    if not record.source.source_type:
        record.source.source_type = spec.source_type
    if not record.source.collection_method:
        record.source.collection_method = spec.plugin_id
    if not record.source.collector:
        record.source.collector = spec.plugin_id

    if context.collection_id:
        record.source.raw_metadata.setdefault("collection_id", context.collection_id)
    if context.arena:
        record.source.raw_metadata.setdefault("arena", context.arena)
    if context.project_id:
        record.source.raw_metadata.setdefault("project_id", context.project_id)

    metadata: dict[str, Any] = {
        "plugin_id": spec.plugin_id,
        "plugin_version": spec.version,
        "collection_id": context.collection_id,
    }
    if context.project_id:
        metadata["project_id"] = context.project_id
    if context.arena:
        metadata["arena"] = context.arena
    if context.cursor:
        metadata["cursor"] = context.cursor
    if context.privacy:
        metadata["privacy"] = dict(context.privacy)

    record.provenance.append(
        CollectionProvenance(
            run_id=context.run_id,
            module=f"collection-plugin:{spec.plugin_id}",
            module_version=spec.version,
            transformations=["plugin-contract-stamp"],
            metadata=metadata,
        )
    )
