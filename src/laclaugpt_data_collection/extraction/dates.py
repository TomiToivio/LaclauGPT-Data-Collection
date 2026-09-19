"""Optional multilingual publication-date normalization."""

from __future__ import annotations

from datetime import datetime
from importlib.metadata import PackageNotFoundError, version


def normalize_date(value: str) -> tuple[datetime | None, dict[str, str | None]]:
    try:
        import dateparser
    except ImportError as exc:
        raise RuntimeError("dateparser is optional; install .[phase1-extraction]") from exc
    try:
        package_version = version("dateparser")
    except PackageNotFoundError:
        package_version = None
    return dateparser.parse(value), {
        "extractor": "dateparser",
        "extractor_version": package_version,
    }
