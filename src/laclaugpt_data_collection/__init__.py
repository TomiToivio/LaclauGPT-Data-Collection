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

__all__ = [
    "CanonicalRecord",
    "CollectionProvenance",
    "ContentSection",
    "MediaReference",
    "NormalizedRecord",
    "SourceSection",
    "canonicalize_source_url",
]
__version__ = "0.1.0"
