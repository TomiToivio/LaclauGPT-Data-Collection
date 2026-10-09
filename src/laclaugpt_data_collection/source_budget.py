# -*- coding: utf-8 -*-
"""Per-source daily ingest caps — enforcing the study's declared source_budgets (#215).

#215 measured that three sources are ~50% of the store and the whole Bluesky
stratum is two individuals' timelines. The mechanism is **differential yield**:
the feed-window rotation is fair (37 feeds are each polled 5-6 times in 24 hourly
ticks), so no source is starved of *polls*. What accumulates is *records*: a
prolific feed or a chatty account emits far more items per poll than a quiet one,
and nothing bounds that.

The study config has always **declared** the bounds — `source_budgets.bluesky.
daily_record_cap`, `.x.daily_record_cap`, etc. — but no code read them. They were
methodology prose, not a mechanism, which is how concentration grew while the
config looked correct.

This module makes a declared daily cap real. It is deliberately a *cap*, not a
reweighting: over-cap records are **deferred**, never silently dropped, and the
deferral is counted and reported so a cap cannot quietly reduce coverage.

Design rules:

- **A cap is a declared number, not a guess.** The module never invents a limit;
  absent means uncapped, and the caller passes what the study config says.
- **The day's count comes from the STORE, not memory.** A bounded collect cycle is
  one process per hour, so a process-local counter resets every tick and would
  never enforce a *daily* cap. The counter therefore counts what the store already
  holds for today — the only place a daily total exists. The count source is
  injected (`count_today`), so the policy is testable without a database.
- **Deferred, not discarded.** An over-cap record is reported with its source
  named, so the daily ledger says "cap reached" rather than showing a source that
  silently stopped.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable


def utc_day(moment: datetime | None = None) -> str:
    """The UTC day a cap applies to. A new day resets the budget with no operator action."""
    return (moment or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime("%Y-%m-%d")


def source_identity(record: dict[str, Any]) -> str:
    """The key a cap applies to: the same identity the corpus audit ranks by."""
    source = record.get("source") or {}
    raw = source.get("raw_metadata") or {}
    for value in (
        raw.get("source_name"),
        source.get("name"),
        record.get("source_name"),
        record.get("author"),
        source.get("author"),
    ):
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


#: A count lookup: (source_identity, utc_day) -> records already stored today.
CountToday = Callable[[str, str], int]


@dataclass
class SourceDailyBudget:
    """Enforces per-source daily caps against counts read from the store.

    ``count_today`` is the only external dependency. In production it is a store
    query (`{project_id, source_name, captured_at >= day-start}`); in tests it is a
    dict lookup. That seam is what lets the policy be verified without a database.
    """

    caps: dict[str, int] = field(default_factory=dict)
    count_today: CountToday | None = None
    day: str | None = None
    #: per-source deferrals observed this cycle, for the cycle report
    deferred: dict[str, int] = field(default_factory=dict)
    #: per-source admissions this cycle (for a cycle log, not for the cap decision)
    admitted: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.caps = {k: int(v) for k, v in (self.caps or {}).items() if v is not None and int(v) > 0}
        self.current_day = self.day or utc_day()

    def _stored_today(self, identity: str) -> int:
        if self.count_today is None:
            return 0
        return int(self.count_today(identity, self.current_day))

    def admit(self, record: dict[str, Any], *, now: datetime | None = None) -> bool:
        """Return True when the record is within its source's daily budget.

        The cap is checked against what the store already holds for today **plus**
        what this cycle has already admitted, so a single cycle cannot blow past a
        cap that spans several ticks. Over-cap records are counted in ``deferred``.
        """
        today = utc_day(now)
        if today != self.current_day:
            self.current_day = today
            self.deferred.clear()
            self.admitted.clear()
        identity = source_identity(record)
        cap = self.caps.get(identity)
        if cap is None:
            return True
        used = self._stored_today(identity) + self.admitted.get(identity, 0)
        if used >= cap:
            self.deferred[identity] = self.deferred.get(identity, 0) + 1
            return False
        self.admitted[identity] = self.admitted.get(identity, 0) + 1
        return True

    def summary(self) -> dict[str, Any]:
        return {
            "day": self.current_day,
            "caps": dict(self.caps),
            "admitted_this_cycle": dict(self.admitted),
            "deferred_this_cycle": dict(self.deferred),
            "deferred_total": sum(self.deferred.values()),
        }


def load_source_caps(
    study_config: str | Path,
    source_identities: Iterable[str],
    *,
    platforms: dict[str, str] | None = None,
) -> dict[str, int]:
    """Map the declared per-platform caps onto ACCOUNT-shaped source identities.

    The study declares caps per platform group (`source_budgets.bluesky.
    daily_record_cap`, `.x.daily_record_cap`). A per-source cap only makes sense
    for an account-shaped platform, where one configured account is one source.

    ``platforms`` maps a source identity to its platform, so a cap is applied only
    to sources that belong to the capped platform. Without it, no caps are
    produced: guessing a platform from a name would invent a bound the study never
    declared, which is the same error as treating a group ceiling as a per-source
    cap. Feed groups are never mapped for that reason --
    `rss_web.daily_relevant_items_soft_cap` is a GROUP total.
    """
    import yaml

    data = yaml.safe_load(Path(study_config).read_text(encoding="utf-8")) or {}
    budgets = data.get("source_budgets") or {}

    def _cap(group: str, *fields: str) -> int | None:
        block = budgets.get(group)
        if not isinstance(block, dict):
            return None
        for f in fields:
            value = block.get(f)
            if isinstance(value, int) and value > 0:
                return value
        return None

    if not platforms:
        return {}
    caps: dict[str, int] = {}
    for group, fields in (
        ("bluesky", ("daily_record_cap",)),
        ("mastodon", ("daily_record_cap",)),
        ("x", ("daily_record_cap", "per_target_per_poll_cap")),
    ):
        cap = _cap(group, *fields)
        if cap is None:
            continue
        for identity in source_identities:
            if platforms.get(identity) == group:
                caps[identity] = cap
    return caps


def budget_report(budget: SourceDailyBudget) -> str:
    """One-line summary for a cycle log."""
    s = budget.summary()
    if not s["caps"]:
        return "source budgets: none declared"
    if not s["deferred_total"]:
        return f"source budgets: {len(s['caps'])} cap(s), none reached on {s['day']}"
    reached = ", ".join(f"{k}+{v}" for k, v in sorted(s["deferred_this_cycle"].items()))
    return (
        f"source budgets: {s['deferred_total']} record(s) over cap on {s['day']} "
        f"({reached}); deferred, not dropped"
    )
