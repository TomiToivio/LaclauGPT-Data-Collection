"""Enriching a headline-only RSS record must add text, not doubt (#416).

A third of the ready RSS stratum stored a title and nothing else, because those feeds syndicate no
body. The repair is a fetch of the article page — which is exactly the kind of step that quietly
corrupts a corpus if it is not pinned:

* the record keeps its identity (same `source_url`, same handoff, same collection provenance);
* the text it gains is traceable to a fetch, through a provenance entry that names the transformation;
* a fetch that returns boilerplate, a paywall or a redirect to a homepage is **skipped**, not applied;
* running twice cannot double the provenance or re-fetch what is already long enough.

These tests run the real fetcher path with a fake transport: no network, and the HTML extraction the
enrichment relies on is the same one the web collector uses.
"""
from __future__ import annotations

from typing import Any

import pytest

from laclaugpt_data_collection.rss_body_enrichment import (
    ENRICHMENT_TRANSFORM,
    MIN_GAIN_CHARS,
    build_patch,
    enrich_record,
    is_useful_gain,
    needs_enrichment,
    select_records,
    stored_text,
    summarise,
)


def record(**overrides: Any) -> dict[str, Any]:
    base = {
        "_id": "rec-1",
        "project_id": "ai26",
        "source_url": "https://www.techpolicy.press/does-the-trump-administration",
        "handoff": {"status": "ready", "published_at": "2026-11-01T00:00:00+00:00"},
        "source": {
            "platform": "rss",
            "raw_metadata": {"source_name": "tech_policy_press"},
        },
        "content": {"text": "Does the Trump administration's campaign to rebrand AI as super-intelligence work?"},
        "human_readable": {"summary": "old", "generated_at": "2026-11-01T00:00:00+00:00"},
        "provenance": [{"module": "rss", "transformations": ["parse-feed"]}],
    }
    base.update(overrides)
    return base


ARTICLE_HTML = """
<html><head><title>Article</title><style>.x{color:red}</style></head>
<body>
  <nav>Home | About | Subscribe</nav>
  <article>
    <h1>Does the campaign work?</h1>
    <p>""" + ("The administration has spent the autumn rebranding its AI agenda as super-intelligence. " * 12) + """</p>
    <p>Officials argue the label signals capability rather than a claim about consciousness.</p>
  </article>
</body></html>
"""

THIN_HTML = "<html><body><nav>Home</nav><p>Subscribe to continue.</p></body></html>"


def test_a_headline_only_record_is_a_candidate():
    assert needs_enrichment(record())


@pytest.mark.parametrize(
    "overrides",
    [
        {"content": {"text": "x" * 400}},                      # already long enough
        {"source": {"platform": "web"}},                        # not an RSS record
        {"handoff": {"status": "rejected"}},                    # not in the analysis frame
        {"source_url": "ftp://example.invalid/x"},              # not fetchable over http(s)
    ],
)
def test_records_that_are_not_candidates(overrides):
    assert not needs_enrichment(record(**overrides))


def test_an_already_enriched_record_is_not_a_candidate():
    enriched = record(provenance=[{"module": "rss", "transformations": [ENRICHMENT_TRANSFORM]}])
    assert needs_enrichment(enriched) is False


def test_a_good_fetch_replaces_the_headline_and_names_the_fetch():
    before = stored_text(record())
    result, patch = enrich_record(record(), fetch=lambda url: (url, ARTICLE_HTML))

    assert result.status == "enriched"
    assert result.chars_after > len(before) * 2
    assert patch is not None
    assert "rebranding its AI agenda" in patch["content.text"]
    assert "color:red" not in patch["content.text"], "CSS is not article text"
    assert "<p>" not in patch["content.text"], "the stored text is text, not markup"
    assert patch["human_readable.summary"].startswith(patch["content.text"][:50])

    prov = patch["provenance"][-1]
    assert prov["transformations"] == [ENRICHMENT_TRANSFORM]
    assert prov["visited_url"] == "https://www.techpolicy.press/does-the-trump-administration"
    assert prov["module"] == "external-link-fetcher"
    assert len(patch["provenance"]) == 2, "the collection provenance stays; enrichment is appended"


def test_a_thin_page_is_skipped_rather_than_stored_as_an_article():
    result, patch = enrich_record(record(), fetch=lambda url: (url, THIN_HTML))
    assert result.status == "skipped"
    assert patch is None
    assert "gain too small" in result.detail


def test_a_failed_fetch_leaves_the_record_untouched():
    result, patch = enrich_record(record(), fetch=lambda url: None)
    assert result.status == "failed"
    assert patch is None


def test_the_gain_rule_needs_both_absolute_and_relative_growth():
    assert is_useful_gain(60, MIN_GAIN_CHARS + 100)
    assert not is_useful_gain(60, MIN_GAIN_CHARS - 1)
    assert not is_useful_gain(400, 500), "1.25x is not an article where a 400-char text already existed"


def test_a_patch_keeps_identity_fields_out_of_the_update():
    patch = build_patch(record(), body_text="x" * 900, final_url="https://example.org/a", fetched_at="2026-11-14T00:00:00+00:00")
    assert "source_url" not in json_keys(patch)
    assert "handoff.status" not in json_keys(patch)
    assert set(patch) == {
        "content.text",
        "human_readable.summary",
        "human_readable.generated_at",
        "provenance",
        "updated_at",
    }


def json_keys(patch: dict[str, Any]) -> set[str]:
    return set(patch)


def test_selection_is_worst_first_and_bounded():
    short = record(_id="a", source_url="https://example.org/a", content={"text": "tiny"})
    medium = record(_id="b", source_url="https://example.org/b", content={"text": "m" * 120})
    long = record(_id="c", source_url="https://example.org/c", content={"text": "l" * 900})
    chosen = select_records([long, medium, short], limit=2)
    assert [row["_id"] for row in chosen] == ["a", "b"]
    assert len(select_records([long, medium, short])) == 2, "the long record is not a candidate"


def test_the_summary_counts_states_and_totals_chars():
    ok_record = record()
    bad_record = record(_id="z", source_url="https://example.org/z")

    def fetch(url: str):
        return (url, ARTICLE_HTML) if "example.org" not in url else None

    results = [
        enrich_record(ok_record, fetch=fetch)[0],
        enrich_record(bad_record, fetch=fetch)[0],
    ]
    summary = summarise(results)
    assert summary["examined"] == 2
    assert summary["counts"] == {"enriched": 1, "failed": 1}
    assert summary["chars_after"] > summary["chars_before"]
    assert len(summary["failures"]) == 1


def test_enrichment_is_idempotent_across_runs():
    _, patch = enrich_record(record(), fetch=lambda url: (url, ARTICLE_HTML))
    assert patch is not None
    enriched = record(
        content={"text": patch["content.text"]},
        provenance=patch["provenance"],
        human_readable={"summary": patch["human_readable.summary"]},
    )
    assert needs_enrichment(enriched) is False
    again, again_patch = enrich_record(enriched, fetch=lambda url: (url, ARTICLE_HTML))
    assert again.status == "not_needed"
    assert again_patch is None
