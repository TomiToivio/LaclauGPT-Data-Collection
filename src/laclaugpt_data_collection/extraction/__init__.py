"""Phase-1-only extraction adapters.

Nothing in this package is imported by Phase 0 collection paths. Optional
third-party packages are imported lazily by the adapter that needs them.
"""

from .html import ExtractionResult, extract_visible_text
from .metadata import extract_structured_metadata

__all__ = ["ExtractionResult", "extract_visible_text", "extract_structured_metadata"]
