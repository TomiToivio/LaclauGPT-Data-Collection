# -*- coding: utf-8 -*-
"""Read-only corpus audit for the AI26 store: coverage and concentration (#207/#208/#215).

Three open issues measure the same store from different angles and each needed a
one-off script to reproduce:

- **#215** -- 3 sources are ~50% of the store and the whole Bluesky stratum is two
  individuals' timelines.
- **#208** -- the grassroots arena is 1.9% of the corpus, Finnish-language
  evidence is 4 unusable records, and 4 of 7 declared platforms produce nothing.
- **#207** -- the X stratum is nominal: 55 records from one 2026-09-16 run, none
  from a configured handle, arena empty, 12 below the publication floor.

Each is a **sampling** finding whose resolution belongs to the author. What this
tool adds is the part that does not: making all three **measurable in one pass,
deterministically**, so the decision is a reading rather than a re-investigation.

Design rules, so a number from here can be trusted:

- **Read-only.** It takes records in memory and returns a dict; it never opens a
  store, writes a file, or contacts a service. The caller supplies the records.
- **Nothing is inferred.** Every bucket has an explicit `unknown` / blank bucket,
  because a share computed over a silently dropped remainder is how a coverage
  gap hides. If 64% of records carry no language, the report says so.
- **No thresholds.** The tool does not decide what "too concentrated" means; it
  reports counts and shares. The one derived fact it states is a plain
  dominance count (`top_n_share`), not a verdict.
- **Denominators are named.** Every ratio is reported with the denominator it
  used, so "1.9% of the corpus" cannot silently change meaning between runs.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Iterable

#: The arenas the paper declares, in a stable reporting order. A record whose
#: arena is none of these is reported under "unknown" rather than dropped.
KNOWN_ARENAS: tuple[str, ...] = ("elites", "grassroots", "parliamentary")

#: Platforms the study config declares, for the declared-but-empty check (#208).
DECLARED_PLATFORMS: tuple[str, ...] = (
    "rss",
    "web",
    "x",
    "arxiv",
    "bluesky",
    "mastodon",
    "youtube",
    "tiktok",
    "instagram",
)

_UNKNOWN = "unknown"
_BLANK = "(blank)"


def _source_field(record: dict[str, Any], *paths: tuple[str, ...]) -> str:
    """Read the first present, non-empty value from a list of nested paths."""
    for path in paths:
        node: Any = record
        for key in path:
            if not isinstance(node, dict):
                node = None
                break
            node = node.get(key)
        if isinstance(node, str) and node.strip():
            return node.strip()
    return ""


def record_arena(record: dict[str, Any]) -> str:
    """Arena, from the top level or portable metadata. '' when absent."""
    value = _source_field(
        record,
        ("arena",),
        ("source", "raw_metadata", "arena"),
        ("provenance",),
    )
    if value:
        return value
    # provenance is a list; check its last entry's metadata
    provenance = record.get("provenance")
    if isinstance(provenance, list) and provenance and isinstance(provenance[-1], dict):
        metadata = provenance[-1].get("metadata") or {}
        if isinstance(metadata, dict):
            arena = metadata.get("arena")
            if isinstance(arena, str) and arena.strip():
                return arena.strip()
    return ""


def record_platform(record: dict[str, Any]) -> str:
    return _source_field(record, ("platform",), ("source", "platform"))


def record_source_name(record: dict[str, Any]) -> str:
    return _source_field(
        record,
        ("source_name",),
        ("source", "raw_metadata", "source_name"),
        ("source", "name"),
    )


def record_author(record: dict[str, Any]) -> str:
    return _source_field(
        record,
        ("author",),
        ("source", "author"),
        ("source", "raw_metadata", "actor_name"),
    )


def record_language(record: dict[str, Any]) -> str:
    return _source_field(record, ("language",), ("source", "language"), ("content", "language"))


def record_publication(record: dict[str, Any]) -> str:
    return _source_field(
        record,
        ("published_at",),
        ("source", "created_at"),
        ("content", "published_at"),
    )


def _shares(counter: Counter[str], total: int) -> list[dict[str, Any]]:
    """Ranked counts with share-of-total, biggest first, ties by name."""
    return [
        {"name": name, "count": count, "share": (count / total) if total else 0.0}
        for name, count in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
    ]


def audit_records(
    records: Iterable[dict[str, Any]],
    *,
    top_n: int = 3,
    publication_floor: str = "",
    configured_sources: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Summarise coverage and concentration over canonical records.

    Parameters
    ----------
    records:
        Canonical record dicts (as persisted). Nothing is mutated.
    top_n:
        The dominance window reported as `top_n_share` (#215 uses 3).
    publication_floor:
        ISO date string; records published before it are counted as
        `off_floor` (#207/#208 need this).
    configured_sources:
        Source names/handles the manifest declares, for the
        "configured but unrepresented" check (#207's core finding).

    Returns a JSON-serialisable report. Every share names its denominator.
    """
    materialized = [r for r in records if isinstance(r, dict)]
    total = len(materialized)

    arena_counts: Counter[str] = Counter(record_arena(r) or _BLANK for r in materialized)
    platform_counts: Counter[str] = Counter(record_platform(r) or _BLANK for r in materialized)
    language_counts: Counter[str] = Counter(record_language(r) or _BLANK for r in materialized)
    source_counts: Counter[str] = Counter(record_source_name(r) or _BLANK for r in materialized)
    author_counts: Counter[str] = Counter(record_author(r) or _BLANK for r in materialized)

    # Bluesky specifically: #215 found the whole stratum is two individuals'
    # timelines, so it needs its own author concentration, not the global one.
    platform_author_counts: dict[str, list[dict[str, Any]]] = {}
    for platform in sorted({record_platform(r) or _BLANK for r in materialized}):
        subset = [r for r in materialized if (record_platform(r) or _BLANK) == platform]
        platform_author_counts[platform] = _shares(
            Counter(record_author(r) or _BLANK for r in subset), len(subset)
        )

    ranked_sources = _shares(source_counts, total)
    top_n_share = sum(entry["count"] for entry in ranked_sources[:top_n]) / total if total else 0.0

    off_floor = 0
    if publication_floor:
        for record in materialized:
            published = record_publication(record)
            if published and published[:10] < publication_floor[:10]:
                off_floor += 1

    configured = [c.strip() for c in (configured_sources or []) if isinstance(c, str) and c.strip()]
    represented = {record_source_name(r) for r in materialized}
    represented |= {record_author(r) for r in materialized}
    unrepresented = sorted(c for c in configured if c not in represented)
    # "checked, none missing" and "never checked" are DIFFERENT facts, and a summary
    # that reports both as `0 unrepresented` hides the difference: a reader sees
    # "0 configured source(s) unrepresented" and concludes the X-stratum check
    # passed, when `--configured-sources` was omitted and nothing was compared at
    # all. #207's core finding is exactly a nominal stratum, so this tool must not
    # be able to fake its own all-clear. `checked` makes the state explicit.
    configured_checked = bool(configured)

    declared_empty = [p for p in DECLARED_PLATFORMS if platform_counts.get(p, 0) == 0]

    arena_shares = {
        arena: (arena_counts.get(arena, 0) / total if total else 0.0)
        for arena in KNOWN_ARENAS
    }

    return {
        "total": total,
        "denominator": {
            "records": total,
            "note": "every share below is count/records; blank and unknown are kept as buckets",
        },
        "by_arena": {
            "counts": {k: v for k, v in arena_counts.items()},
            "shares": arena_shares,
            "unknown": arena_counts.get(_BLANK, 0) + arena_counts.get(_UNKNOWN, 0),
        },
        "by_platform": {
            "counts": {k: v for k, v in platform_counts.items()},
            "declared": list(DECLARED_PLATFORMS),
            "declared_but_empty": declared_empty,
        },
        "by_language": {
            "counts": {k: v for k, v in language_counts.items()},
            "unlabelled": language_counts.get(_BLANK, 0),
        },
        "by_source": {"ranked": ranked_sources},
        "by_author": {
            "ranked": _shares(author_counts, total),
            "per_platform": platform_author_counts,
        },
        "concentration": {
            "top_n": top_n,
            "top_n_share": top_n_share,
            "top_n_names": [entry["name"] for entry in ranked_sources[:top_n]],
            "denominator": total,
        },
        "publication_floor": {
            "floor": publication_floor,
            "off_floor": off_floor,
        },
        "configured_sources": {
            "configured": len(configured),
            "checked": configured_checked,
            "unrepresented": unrepresented,
            "unrepresented_count": len(unrepresented),
        },
    }


def audit_summary(report: dict[str, Any]) -> str:
    """One-line summary for a log line or issue comment.

    The configured-source clause must distinguish "checked, none missing" from
    "not checked": reporting both as `0 ... unrepresented` is how #207's nominal
    stratum would read as an all-clear.
    """
    configured = report["configured_sources"]
    if configured.get("checked"):
        configured_clause = (
            f"{configured['unrepresented_count']} of {configured['configured']} "
            "configured source(s) unrepresented"
        )
    else:
        configured_clause = "configured-source check not run (pass --configured-sources)"
    return (
        f"corpus audit: {report['total']} records | "
        f"grassroots {report['by_arena']['shares'].get('grassroots', 0.0):.1%}, "
        f"unknown-arena {report['by_arena']['unknown']} | "
        f"top-{report['concentration']['top_n']} share "
        f"{report['concentration']['top_n_share']:.1%} | "
        f"{report['by_language']['unlabelled']} without language | "
        f"{configured_clause} | "
        f"{len(report['by_platform']['declared_but_empty'])} declared platform(s) empty"
    )
