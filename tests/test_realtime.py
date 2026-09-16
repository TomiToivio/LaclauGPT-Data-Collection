from laclaugpt_data_collection.realtime import (
    RealtimePolicy,
    analysis_eligibility,
    extract_external_urls,
    mark_realtime_metadata,
    prepare_analysis_candidates,
    web_child_record,
)


def rec(url: str, platform: str, published: str | None, *, arena: str = "elites") -> dict:
    return {
        "source_url": url,
        "collection_id": "ai26",
        "arena": arena,
        "source": {"platform": platform, "created_at": published},
    }


def test_ai26_date_floor_and_missing_time_are_explicit():
    policy = RealtimePolicy.ai26()
    assert analysis_eligibility(rec("https://e/x", "web", "2026-08-31T23:59:59Z"), policy) == (
        False,
        "before_publication_date_floor",
    )
    assert analysis_eligibility(rec("https://e/y", "web", "2026-09-01T00:00:00Z"), policy) == (
        True,
        "eligible",
    )
    assert analysis_eligibility(rec("https://e/z", "web", None), policy) == (
        False,
        "missing_source_publication_time",
    )


def test_priority_is_source_tier_then_newest_first_then_stable_id():
    policy = RealtimePolicy.ai26()
    records = [
        rec("https://x.com/example/status/1", "x", "2026-09-16T12:00:00Z"),
        rec("https://example.org/older", "web", "2026-09-15T12:00:00Z"),
        rec("https://example.org/newer-b", "web", "2026-09-16T10:00:00Z"),
        rec("https://example.org/newer-a", "web", "2026-09-16T10:00:00Z"),
    ]
    ordered = prepare_analysis_candidates(records, policy)
    assert [item["source_url"] for item in ordered] == [
        "https://example.org/newer-a",
        "https://example.org/newer-b",
        "https://example.org/older",
        "https://x.com/example/status/1",
    ]
    assert ordered[-1]["source_priority"] == 3


def test_new_non_x_overtakes_x_backlog():
    policy = RealtimePolicy.ai26()
    ordered = prepare_analysis_candidates(
        [
            rec("https://x.com/example/status/old", "x", "2026-09-01T01:00:00Z"),
            rec("https://news.example/current", "rss", "2026-09-16T12:00:00Z"),
        ],
        policy,
    )
    assert ordered[0]["source_url"] == "https://news.example/current"


def test_external_links_become_web_children_with_parent_and_arena_provenance():
    parent = rec("https://x.com/example/status/42", "x", "2026-09-16T12:00:00Z", arena="grassroots")
    text = "Read https://example.org/article?utm_source=x and https://x.com/help plus https://example.org/article?utm_source=x"
    links = extract_external_urls(text, originating_url=parent["source_url"])
    assert links == ["https://example.org/article"]
    child = web_child_record(links[0], parent)
    assert child["source"]["source_type"] == "WEB"
    assert child["source"]["parent_source_url"] == parent["source_url"]
    assert child["collection_id"] == "ai26"
    assert child["arena"] == "grassroots"


def test_arenas_share_one_collection_id():
    elites = mark_realtime_metadata({"source_url": "urn:a"}, collection_id="ai26", arena="elites")
    grass = mark_realtime_metadata({"source_url": "urn:b"}, collection_id="ai26", arena="grassroots")
    parliament = mark_realtime_metadata({"source_url": "urn:c"}, collection_id="ai26", arena="parliamentary")
    assert {item["collection_id"] for item in (elites, grass, parliament)} == {"ai26"}
    assert {item["arena"] for item in (elites, grass, parliament)} == {"elites", "grassroots", "parliamentary"}
