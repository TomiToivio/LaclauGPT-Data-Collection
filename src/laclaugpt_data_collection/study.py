"""Study configuration loading (accounts, window, platform toggles).

Adapted from the public `collector/config.py` in
TomiToivio/LaclauGPT-Discourse-Analysis. Study configs with real target
lists are sensitive operational configuration: they stay in ignored local
files. Only synthetic templates/examples are committed.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml


class StudyConfig:
    """Parsed study config: window, platforms, candidates, parties, groups."""

    def __init__(self, data: dict[str, Any], source: str) -> None:
        self.source = source
        window = data.get("window") or {}
        self.start: date = _date(window.get("start"))
        self.end: date = _date(window.get("end"))
        self.timezone = data.get("timezone", "UTC")
        self.collection_policy: dict[str, Any] = dict(data.get("collection_policy") or {})
        platforms = data.get("platforms") or {}
        self.platforms = [p for p, cfg in platforms.items()
                          if isinstance(cfg, dict) and cfg.get("enabled")]
        self.platform_urls = {p: (cfg.get("base_urls") or [])
                              for p, cfg in platforms.items()
                              if isinstance(cfg, dict)}
        self.candidates: list[dict] = list(data.get("candidates") or [])
        self.parties: list[dict] = list(data.get("parties") or [])
        self.groups: list[dict] = [
            g for g in (data.get("groups") or []) if isinstance(g, dict)]
        self._reject_invalid_handles()
        self.expected_candidates = int(data.get("expected_candidates",
                                                _infer_expected(data)))
        self.study = data.get("study", "unnamed")

    @property
    def fetch_external_links_as_web_sources(self) -> bool:
        """Whether post-write external links should be fetched as WEB children."""
        return bool(self.collection_policy.get("fetch_external_links_as_web_sources", False))

    @property
    def link_fetch_failure_blocks_parent(self) -> bool:
        """Failure policy. Public reference configs should normally keep this false."""
        return bool(self.collection_policy.get("link_fetch_failure_blocks_parent", False))

    def _reject_invalid_handles(self) -> None:
        """Fail visibly on empty/whitespace/non-string handles (no silent fixes)."""
        bad: list[str] = []
        for entity in self.candidates + self.parties:
            handles = entity.get("handles") or entity.get("accounts") or {}
            for platform, values in handles.items():
                for value in values or []:
                    if not isinstance(value, str) or not value.strip():
                        bad.append(f"{entity.get('name', '?')}/{platform}: {value!r}")
        for group in self.groups:
            handles = group.get("accounts") or group.get("handles") or {}
            for platform, values in handles.items():
                for value in values or []:
                    if not isinstance(value, str) or not value.strip():
                        bad.append(f"{group.get('id', '?')}/{platform}: {value!r}")
        if bad:
            raise ValueError(
                "study config contains empty/whitespace/non-string handles "
                "(handles are never silently corrected): " + "; ".join(bad))

    def accounts(self) -> list[dict]:
        """All collection targets as flat (name, kind, platform, handle) rows."""
        rows: list[dict] = []
        for kind, group in (("candidate", self.candidates), ("party", self.parties)):
            for entity in group:
                handles = entity.get("handles") or entity.get("accounts") or {}
                for platform in self.platforms:
                    for handle in handles.get(platform) or []:
                        rows.append({"name": entity["name"], "kind": kind,
                                     "platform": platform, "handle": handle,
                                     "group_id": kind,
                                     "formation_seed": entity.get("formation_seed", "")})
        for group in self.groups:
            handles = group.get("accounts") or group.get("handles") or {}
            for platform in self.platforms:
                for handle in handles.get(platform) or []:
                    rows.append({
                        "name": group.get("name") or group.get("id", ""),
                        "kind": "group",
                        "platform": platform, "handle": handle,
                        "group_id": group.get("id", ""),
                        "formation_seed": _formation_seed(group),
                        "arena": group.get("arena", ""),
                        "notes": group.get("notes", ""),
                    })
        return rows

    def local_today(self) -> date:
        try:
            tz = ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError:
            tz = timezone.utc
        return datetime.now(tz).date()

    def in_window(self, today: date | None = None) -> bool:
        return self.start <= (today or self.local_today()) <= self.end

    def missing_candidates(self) -> list[str]:
        if self.expected_candidates <= 0:
            return []
        have = {c["name"] for c in self.candidates}
        return [f"expected {self.expected_candidates} candidates, "
                f"{len(have)} configured"] if len(have) < self.expected_candidates else []


def _date(value: Any) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _formation_seed(group: dict) -> str:
    seed = group.get("formation_seed")
    return "" if seed is None else str(seed)


def _infer_expected(data: dict) -> int:
    return 7 if (data.get("candidates") or data.get("parties")) else 0


def load_config(path: str | Path) -> StudyConfig:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"collector config {path!s} must contain a YAML mapping")
    return StudyConfig(data, str(path))
