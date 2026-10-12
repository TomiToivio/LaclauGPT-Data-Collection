# -*- coding: utf-8 -*-
"""Issue #249 contract: a declared arena platform must be collectable.

A study must not declare a stratum it cannot collect. For every arena in the
AI26 study config, each platform named in that arena's ``platforms:`` list must
have at least one ACTIVE row in the source manifest (``ai26.sources.example.toml``)
whose ``arena`` is that arena. A row carrying ``active = false`` (or
``enabled = false``) cannot feed anything, and neither can a platform with no
row at all for the arena.

This is the guard that would have caught the original defect (#249): ``youtube``
was declared in all three arenas' platform lists while every ``[[youtube_source]]``
row was inactive, so no youtube record could ever arrive.

Pure config/data contract: it asserts nothing about prose or documentation.
"""
from __future__ import annotations

import tomllib
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
MANIFEST = REPO / "configs" / "studies" / "ai26.sources.example.toml"

# The deployed runtime study config is gitignored, so the tracked audited plan is
# the committable copy. Check every study config that exists on this checkout
# (both on Laskin; only the tracked plan in CI).
STUDY_CANDIDATES = (
    REPO / "configs" / "studies" / "ai26.example.yaml",
    REPO / "data" / "config" / "ai26.yaml",
)

# Source-manifest table -> the platform its rows feed the corpus as.
TABLE_PLATFORM = {
    "feed": "rss",
    "web_source": "web",
    "x_account": "x",
    "bluesky_account": "bluesky",
    "mastodon_account": "mastodon",
    "youtube_source": "youtube",
    "scholarly_query": "scholarly",
}


def _active(row: dict) -> bool:
    """A row runs unless it is explicitly disabled.

    Mirrors the runner's loader (``row.get("enabled", row.get("active", True))``).
    """
    return row.get("enabled", row.get("active", True)) is not False


def collectable_pairs() -> set[tuple[str, str]]:
    """(arena, platform) pairs with >=1 ACTIVE manifest row able to feed them."""
    data = tomllib.loads(MANIFEST.read_text(encoding="utf-8"))
    pairs: set[tuple[str, str]] = set()
    for table, platform in TABLE_PLATFORM.items():
        for row in data.get(table) or []:
            if not _active(row):
                continue
            arena = str(row.get("arena") or "").strip()
            if arena:
                pairs.add((arena, platform))
    return pairs


def test_every_declared_arena_platform_has_an_active_source() -> None:
    pairs = collectable_pairs()
    checked = 0
    for path in STUDY_CANDIDATES:
        if not path.exists():
            continue
        checked += 1
        study = yaml.safe_load(path.read_text(encoding="utf-8"))
        for arena, config in (study.get("arenas") or {}).items():
            declared = list(config.get("platforms") or [])
            missing = sorted(p for p in declared if (arena, p) not in pairs)
            assert not missing, (
                f"{path.name}: arena {arena!r} declares platform(s) {missing} but "
                "no ACTIVE source row in the manifest can feed them (#249)"
            )
    assert checked, "no AI26 study config found to check"
