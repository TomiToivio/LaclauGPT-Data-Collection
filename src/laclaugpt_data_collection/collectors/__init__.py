"""Collection sources and capture ingestion."""
from typing import Any

from .arxiv import ArxivCollector
from .base import CollectionResult, Collector
from .bluesky import BlueskyCollector
from .mastodon import MastodonCollector
from .rss import RSSCollector
from .spool import DirectorySpool
from .telegram import TelegramCollector
from .x_apify import XApifyCollector
from .youtube import YouTubeCollector


def ingest_capture(*args: Any, **kwargs: Any) -> Any:
    """Lazy public wrapper avoiding normalization/parser import cycles."""
    from .ingest import ingest_capture as implementation

    return implementation(*args, **kwargs)


def platform_from_url(*args: Any, **kwargs: Any) -> Any:
    from .ingest import platform_from_url as implementation

    return implementation(*args, **kwargs)


__all__ = [
    "ArxivCollector",
    "BlueskyCollector",
    "CollectionResult",
    "Collector",
    "DirectorySpool",
    "MastodonCollector",
    "RSSCollector",
    "TelegramCollector",
    "XApifyCollector",
    "YouTubeCollector",
    "ingest_capture",
    "platform_from_url",
]
