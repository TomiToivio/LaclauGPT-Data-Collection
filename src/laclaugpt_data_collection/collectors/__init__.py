"""Collection sources and capture ingestion."""

from .base import CollectionResult, Collector
from .bluesky import BlueskyCollector
from .ingest import ingest_capture, platform_from_url
from .rss import RSSCollector

__all__ = [
    "BlueskyCollector",
    "CollectionResult",
    "Collector",
    "RSSCollector",
    "ingest_capture",
    "platform_from_url",
]
