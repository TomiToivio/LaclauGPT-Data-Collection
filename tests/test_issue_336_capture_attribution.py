"""A capture keeps the actor→arena relation the study config already knows (issue #336).

40% of the analysis-grade corpus carried no `arena`. The mapping existed in the study config
(`groups[].accounts` → `arena`), was used to build the tour URL list, and was then dropped: the
records the capture server stored had no `arena` and no `source.name`, and external-link children
inherited the blank. These tests pin the relation at the two places it has to survive — the URL →
configured-row lookup, and the record the normaliser builds.

No live capture, no server, no Mongo: a row list shaped like `StudyConfig.accounts()` and one
mapped X item are enough.
"""
from __future__ import annotations

import pytest

from laclaugpt_data_collection.attribution import UNATTRIBUTED, attribution_for, match_account
from laclaugpt_data_collection.normalize import normalise

ROWS = [
    {
        "name": "PauseAI",
        "kind": "group",
        "platform": "x",
        "handle": "PauseAI",
        "group_id": "grassroots_pause_resistance_x",
        "arena": "grassroots",
    },
    {
        "name": "Anthropic",
        "kind": "group",
        "platform": "x",
        "handle": "AnthropicAI",
        "group_id": "frontier_labs_x",
        "arena": "elites",
    },
    {
        "name": "Valtioneuvosto",
        "kind": "group",
        "platform": "rss",
        "handle": "valtioneuvosto",
        "group_id": "governance_institutions",
        "arena": "parliamentary",
    },
]

X_PAGE = "https://x.com/PauseAI"


def _mapped(handle: str = "PauseAI") -> dict:
    return {
        "id": "1900000000000000001",
        "author": handle,
        "body": "A synthetic post about deployment pauses.",
        "timestamp": "2026-10-01T09:00:00Z",
        "link": f"https://x.com/{handle}/status/1900000000000000001",
    }


@pytest.mark.parametrize(
    "url", [X_PAGE, f"{X_PAGE}/", "https://x.com/@PauseAI", "https://twitter.com/pauseai"]
)
def test_a_page_url_resolves_to_its_configured_row(url: str) -> None:
    assert match_account(ROWS, "x", url) is ROWS[0]


def test_the_handle_is_compared_without_the_at_sign_or_case() -> None:
    assert match_account(ROWS, "x", "https://x.com/@pauseai") is ROWS[0]
    assert match_account(ROWS, "X", X_PAGE) is ROWS[0]


def test_a_page_for_another_platform_does_not_match() -> None:
    """The same handle on a different platform is a different source row."""
    assert match_account(ROWS, "rss", X_PAGE) is None


def test_an_unknown_handle_is_unattributed_and_invents_nothing() -> None:
    result = attribution_for(ROWS, "x", "https://x.com/somebody_else")
    assert result == {"account": UNATTRIBUTED, "source_name": "", "arena": "", "group_id": ""}
    assert match_account(ROWS, "x", "https://x.com/somebody_else") is None


def test_the_account_keeps_its_historical_shape() -> None:
    result = attribution_for(ROWS, "x", X_PAGE)
    assert result["account"] == "PauseAI:PauseAI"
    assert result["arena"] == "grassroots"
    assert result["source_name"] == "PauseAI"


def test_a_normalised_record_carries_arena_and_source_name() -> None:
    """The child-inheritance path reads `source.raw_metadata['arena']`, so this is where it lives."""
    attribution = attribution_for(ROWS, "x", X_PAGE)
    record = normalise("x", _mapped(), metadata={"captured_at": "2026-10-01T09:00:00Z", **attribution})

    assert record.source.raw_metadata["arena"] == "grassroots"
    assert record.source.raw_metadata["group_id"] == "grassroots_pause_resistance_x"
    assert record.source.raw_metadata["source_name"] == "PauseAI"


def test_an_unattributed_record_stays_blank_rather_than_guessed() -> None:
    record = normalise("x", _mapped("somebody_else"), metadata={"captured_at": "2026-10-01T09:00:00Z"})

    assert "arena" not in record.source.raw_metadata
    assert "source_name" not in record.source.raw_metadata


def test_the_capture_metadata_survives_a_round_trip_into_the_canonical_record() -> None:
    """A record built by the same path the capture server uses keeps the attribution verbatim."""
    attribution = attribution_for(ROWS, "x", "https://x.com/@AnthropicAI")
    record = normalise(
        "x", _mapped("AnthropicAI"), metadata={"captured_at": "2026-10-01T09:00:00Z", **attribution}
    )
    payload = record.model_dump(mode="json")

    assert payload["source"]["raw_metadata"]["arena"] == "elites"
    assert payload["source"]["raw_metadata"]["source_name"] == "Anthropic"
