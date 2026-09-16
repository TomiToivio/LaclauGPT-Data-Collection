"""LaclauGPT data collection public API."""

from .models import (
    CanonicalRecord,
    CollectionProvenance,
    ContentSection,
    MediaReference,
    NormalizedRecord,
    SourceSection,
    canonicalize_source_url,
)
from .plugins import (
    CollectionContext,
    CollectionPlugin,
    CollectionRunner,
    PluginRegistry,
    PluginRunResult,
    PluginSpec,
    adapt_collector,
    default_registry,
)

__all__ = [
    "CanonicalRecord",
    "CollectionContext",
    "CollectionPlugin",
    "CollectionProvenance",
    "CollectionRunner",
    "ContentSection",
    "MediaReference",
    "NormalizedRecord",
    "PluginRegistry",
    "PluginRunResult",
    "PluginSpec",
    "SourceSection",
    "adapt_collector",
    "canonicalize_source_url",
    "default_registry",
]
__version__ = "0.1.0"
