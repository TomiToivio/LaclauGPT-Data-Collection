"""Explicit AI26 source identity corrections, not ideological classifications."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

MIRI_WRONG_ACCOUNT_REASON = "ai26_wrong_miri_account"
_X_HOSTS = {"x.com", "twitter.com", "www.x.com", "www.twitter.com", "mobile.x.com", "mobile.twitter.com"}


def x_status_handle(url: str) -> str:
    """Return an evidenced handle on an X status URL, or an empty string."""
    try:
        parts = urlsplit(url)
        fields = parts.path.strip("/").split("/")
        if (
            parts.hostname in _X_HOSTS and len(fields) == 3
            and fields[1] == "status" and fields[2].isdigit()
            and fields[0].casefold() != "i"
        ):
            return fields[0].casefold()
    except ValueError:
        pass
    return ""


def is_wrong_miri_account(record: Mapping[str, Any]) -> bool:
    """Only exclude a URL-confirmed old X identity, never a mention or conflicting author."""
    source = record.get("source") or {}
    platform = str(source.get("platform") or "").casefold()
    author = str(source.get("author") or "").strip().lstrip("@").casefold()
    handle = x_status_handle(str(record.get("source_url") or ""))
    return (
        platform in {"", "x", "twitter"}
        and handle == "miri_ai"
        and author in {"", handle}
    )
