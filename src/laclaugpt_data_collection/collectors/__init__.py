"""Collection sources and capture ingestion."""
from typing import Any

from .base import CollectionResult, Collector
from .bluesky import BlueskyCollector
from .rss import RSSCollector


def ingest_capture(*args: Any, **kwargs: Any) -> Any:
    """Lazy public wrapper avoiding normalization/parser import cycles."""
    from .ingest import ingest_capture as implementation
    return implementation(*args, **kwargs)

def platform_from_url(*args: Any, **kwargs: Any) -> Any:
    from .ingest import platform_from_url as implementation
    return implementation(*args, **kwargs)

__all__ = ["BlueskyCollector", "CollectionResult", "Collector", "RSSCollector", "ingest_capture", "platform_from_url"]
