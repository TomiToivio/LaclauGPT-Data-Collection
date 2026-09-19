"""Optional structured metadata extraction for Phase 1."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from typing import Any


def _version(name: str) -> str | None:
    try:
        return version(name)
    except PackageNotFoundError:
        return None


def extract_structured_metadata(html: str, *, base_url: str) -> dict[str, Any]:
    """Extract JSON-LD/OpenGraph/microdata with lazy extruct import."""
    try:
        import extruct
    except ImportError as exc:
        raise RuntimeError("extruct is optional; install .[phase1-extraction]") from exc
    data = extruct.extract(
        html,
        base_url=base_url,
        syntaxes=["json-ld", "opengraph", "microdata"],
        uniform=True,
    )
    return {
        "metadata": data,
        "provenance": {
            "extractor": "extruct",
            "extractor_version": _version("extruct"),
            "source_url": base_url,
        },
    }
