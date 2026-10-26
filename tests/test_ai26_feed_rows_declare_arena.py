# -*- coding: utf-8 -*-
"""Issue #265 contract: every declared ``[[feed]]`` row declares its arena status.

The defect this pins: ten ``[[feed]]`` rows carried **no** ``arena`` key at all,
while every other row kind always declared one. Nothing failed, ``manifest-drift``
compared the deployed manifest against the tracked plan and found them identical,
and the only visible symptom was arena-blank records diluting the arena-stratified
shares reported in §4.1 of the paper.

The contract, therefore:

* every ``[[feed]]`` row declares its arena status **explicitly** -- either a real
  arena or an explicit "not assigned, and that is a sampling decision awaiting the
  author" marker with a reason. An omission is a failure, not a default.
* a declared arena is one of the study's arenas; the vocabulary is imported from
  the corpus audit rather than restated here.
* a row that cannot produce a record is disabled with a documented reason, and it
  is disabled through ``enabled`` -- the field the feed loader actually reads.

Pure config/data contract: it asserts nothing about prose or documentation.
"""
from __future__ import annotations

import tomllib
from pathlib import Path

from laclaugpt_data_collection.corpus_audit import KNOWN_ARENAS

REPO = Path(__file__).resolve().parents[1]
MANIFEST = REPO / "configs" / "studies" / "ai26.sources.example.toml"


def feed_rows() -> list[dict]:
    data = tomllib.loads(MANIFEST.read_text(encoding="utf-8"))
    return list(data.get("feed") or [])


def test_every_feed_row_declares_its_arena_status() -> None:
    """No row may leave the arena question open by omission (#265)."""
    undeclared: list[str] = []
    for row in feed_rows():
        arena = str(row.get("arena") or "").strip()
        if arena:
            continue
        if row.get("arena_unassigned") is True and str(
            row.get("arena_unassigned_reason") or ""
        ).strip():
            continue
        undeclared.append(str(row.get("name") or "<unnamed>"))
    assert not undeclared, (
        "feed row(s) declare neither an `arena` nor an explicit "
        f"`arena_unassigned` with a reason: {sorted(undeclared)} (#265). An omitted "
        "arena is what let records dilute the arena-stratified shares unnoticed."
    )


def test_a_declared_arena_is_one_of_the_study_arenas() -> None:
    """The arena vocabulary is the audit's, not a second one invented here."""
    known = set(KNOWN_ARENAS)
    bad = sorted(
        {str(row.get("arena")).strip() for row in feed_rows()
         if str(row.get("arena") or "").strip()} - known
    )
    assert not bad, f"feed row(s) declare an arena outside {sorted(known)}: {bad}"


def test_an_unassigned_row_is_not_also_given_an_arena() -> None:
    """The marker is not a fallback for a row whose arena is actually known."""
    both = sorted(
        str(row.get("name") or "<unnamed>") for row in feed_rows()
        if row.get("arena_unassigned") is True and str(row.get("arena") or "").strip()
    )
    assert not both, f"feed row(s) declare both an arena and `arena_unassigned`: {both}"


def test_a_disabled_feed_row_documents_why() -> None:
    """A row taken out of the schedule keeps its sampling intention and a reason."""
    undocumented = sorted(
        str(row.get("name") or "<unnamed>") for row in feed_rows()
        if row.get("enabled") is False and not str(row.get("inactive_reason") or "").strip()
    )
    assert not undocumented, (
        f"feed row(s) are disabled without an `inactive_reason`: {undocumented} (#265)"
    )


def test_a_disabled_feed_row_retains_its_sampling_intention() -> None:
    """Disabling must not be a quiet retirement: the row keeps its provenance fields."""
    incomplete: list[str] = []
    for row in feed_rows():
        if row.get("enabled") is not False:
            continue
        missing = [
            field for field in ("name", "feed_url", "arena", "source_family", "priority")
            if not str(row.get(field) or "").strip() and not (
                field == "arena" and row.get("arena_unassigned") is True
            )
        ]
        if missing:
            incomplete.append(f"{row.get('name')}: missing {missing}")
    assert not incomplete, (
        "disabled feed row(s) dropped provenance the manifest needs to retain the "
        f"sampling intention (#249 pattern): {incomplete}"
    )


def test_feeds_are_disabled_through_the_field_the_loader_reads() -> None:
    """`load_feed_manifest` honours `enabled`; `active` is not consulted for feeds.

    A row disabled with ``active = false`` would look disabled in a review and keep
    polling in production -- a silent declaration, which is the class of defect this
    whole family of guards exists for.
    """
    silently_disabled = sorted(
        str(row.get("name") or "<unnamed>") for row in feed_rows()
        if row.get("active") is False and row.get("enabled") is not False
    )
    assert not silently_disabled, (
        "feed row(s) set `active = false`, which the feed loader does not read, "
        f"without `enabled = false`: {silently_disabled}. Use `enabled`."
    )


def test_known_stale_feeds_are_actually_disabled() -> None:
    """Prevent source publication-floor exclusions from being polled forever."""
    by_name = {row["name"]: row for row in feed_rows()}
    for name in ("marc_andreessen", "yudkowsky_net", "kaifulee_medium",
                 "public_ai_network", "ada_lovelace", "data_society"):
        assert by_name[name].get("enabled") is False, name
        assert by_name[name].get("inactive_reason"), name


def test_reactivated_feed_is_enabled_and_records_the_verification() -> None:
    """`petterijarvinen` was re-activated on 2026-10-26 after the publisher resumed.

    Its disable condition (#265) was explicitly "re-verify if publisher resumes".
    Two items dated 2026-10-16 are past the publication floor, so the row must poll
    again and must carry the date it was last verified -- otherwise the next audit
    cannot tell a deliberate re-activation from an accidental one.
    """
    by_name = {row["name"]: row for row in feed_rows()}
    row = by_name["petterijarvinen"]
    assert row.get("enabled") is True
    assert row.get("last_verified") == "2026-10-26"
    assert row.get("inactive_reason") is None
