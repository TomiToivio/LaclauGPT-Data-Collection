"""The #336 backfill plans exactly the fields it claims, and invents nothing (#336).

The capture-side fix (#345) gives new X records their arena. The records captured before it still
carry a blank one, and this is the planning half of filling them: one pure function, fed a stored
document and the study's declared account rows.

No Mongo, no network: the document shapes below are the ones the store holds.
"""
from __future__ import annotations

import pytest

from laclaugpt_data_collection.arena_backfill import plan_update
from laclaugpt_data_collection.attribution import match_account

ROWS = [
    {"name": "PauseAI", "platform": "x", "handle": "PauseAI",
     "group_id": "grassroots_pause_resistance_x", "arena": "grassroots"},
    {"name": "Anthropic", "platform": "x", "handle": "AnthropicAI",
     "group_id": "frontier_labs_x", "arena": "elites"},
    {"name": "Valtioneuvosto", "platform": "rss", "handle": "valtioneuvosto",
     "group_id": "governance_institutions", "arena": "parliamentary"},
]


def _document(handle: str = "PauseAI", *, arena: str = "", metadata: dict | None = None) -> dict:
    raw = {"collection_id": "ai26", "unix_timestamp": 1759312800}
    raw.update(metadata or {})
    if arena:
        raw["arena"] = arena
    return {
        "source_url": f"https://x.com/{handle}/status/1",
        "arena": arena,
        "source": {"platform": "x", "author": handle, "raw_metadata": raw},
    }


@pytest.mark.parametrize(
    "url",
    ["https://x.com/PauseAI", "https://x.com/PauseAI/", "https://x.com/@PauseAI",
     "https://twitter.com/pauseai", "https://x.com/PAUSEAI/status/1"],
)
def test_the_handle_resolves_the_declared_row(url: str) -> None:
    assert match_account(ROWS, "x", url) is ROWS[0]


def test_the_same_handle_on_another_platform_is_a_different_source() -> None:
    assert match_account(ROWS, "rss", "https://x.com/PauseAI") is None
    assert match_account(ROWS, "x", "https://rss.example.invalid/valtioneuvosto") is None


def test_a_blank_arena_gets_the_declared_arena_and_labels() -> None:
    update = plan_update(_document(), ROWS)
    assert update == {
        "arena": "grassroots",
        "source.raw_metadata.arena": "grassroots",
        "source.raw_metadata.source_name": "PauseAI",
    }


def test_an_existing_value_is_never_overwritten() -> None:
    document = _document(arena="elites", metadata={"arena": "elites", "source_name": "kept"})
    assert plan_update(document, ROWS) is None

    partial = _document(metadata={"source_name": "kept"})
    assert plan_update(partial, ROWS) == {
        "arena": "grassroots",
        "source.raw_metadata.arena": "grassroots",
    }


def test_an_unknown_handle_is_not_attributed() -> None:
    assert plan_update(_document("somebody_else"), ROWS) is None


def test_a_record_without_an_author_is_not_attributed() -> None:
    document = _document()
    document["source"]["author"] = ""
    assert plan_update(document, ROWS) is None


def test_only_x_records_are_considered() -> None:
    document = _document()
    document["source"]["platform"] = "web"
    assert plan_update(document, ROWS) is None


def test_the_plan_is_idempotent() -> None:
    """Applying the plan once makes the second plan empty — the run can be repeated safely."""
    document = _document()
    update = plan_update(document, ROWS)
    assert update is not None
    for key, value in update.items():
        if key == "arena":
            document["arena"] = value
        else:
            document["source"]["raw_metadata"][key.rsplit(".", 1)[1]] = value
    assert plan_update(document, ROWS) is None
