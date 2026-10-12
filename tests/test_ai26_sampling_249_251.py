"""Regression checks for explicit AI26 sampling decisions (#249, #251)."""
import tomllib
from pathlib import Path

from laclaugpt_data_collection.ai26_laskin_runner import (
    _WEB_SOURCE_FEED_FALLBACKS,
    load_non_browser_jobs,
)
from laclaugpt_data_collection.server_runner import load_feed_manifest

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "configs/studies/ai26.sources.example.toml"


def test_impossible_strata_retained_as_inactive_not_silently_reassigned():
    data = tomllib.loads(PATH.read_text(encoding="utf-8"))
    dead_scholarly = {"critical_ai_political_economy", "ai_creative_labour", "left_techno_optimism"}
    rows = {row["name"]: row for row in data["scholarly_query"]}
    assert dead_scholarly <= rows.keys()
    for name in dead_scholarly:
        assert rows[name]["active"] is False
        assert "arxiv" not in {s.lower() for s in rows[name]["services"]}
        assert rows[name]["inactive_reason"]
    assert len(data["youtube_source"]) == 5
    assert all(row["active"] is False and row["inactive_reason"] for row in data["youtube_source"])
    jobs = load_non_browser_jobs(PATH)
    assert not any(job["kind"] == "youtube_source" for job in jobs)
    assert not any(job["kind"] == "scholarly_query" and job["name"] in dead_scholarly for job in jobs)
    assert {"frontier_ai_safety", "ai_governance"} <= {
        job["name"] for job in jobs if job["kind"] == "scholarly_query"
    }


def test_microsoft_first_party_feed_is_active_elites_source():
    data = tomllib.loads(PATH.read_text(encoding="utf-8"))
    # Exactly one Microsoft identity in the sampling frame (#256): the duplicate
    # [[feed]] row added by #252 was removed, leaving the [[web_source]] row that #251
    # itself recommended and that the browser-free stage reaches through the fallback
    # map below.
    identity = [
        (table, row)
        for table in ("feed", "web_source")
        for row in data.get(table, [])
        if row["name"] == "microsoft_ai_blog"
    ]
    assert len(identity) == 1
    (table, row), = identity
    assert table == "web_source"
    assert row["arena"] == "elites"
    # No `active`/`enabled` key means the row runs; the non-browser loader agrees.
    assert row.get("enabled", row.get("active", True)) is not False
    jobs = [job for job in load_non_browser_jobs(PATH) if job["name"] == "microsoft_ai_blog"]
    assert len(jobs) == 1 and jobs[0]["kind"] == "web_source"
    # The verified feed is reachable without a browser via the runner's fallback map.
    assert _WEB_SOURCE_FEED_FALLBACKS[row["homepage"].rstrip("/")] == (
        "https://www.microsoft.com/en-us/ai/blog/feed/"
    )
    # A [[feed]] row is not a non-browser job: the Laskin non-browser loader only
    # serves the web_source/social/scholarly tables, and feeds are collected by the
    # RSS path (server_runner.load_feed_manifest). Assert the surviving identity is
    # not double-scheduled as a job nor loaded as an RSS feed.
    assert not any(job["kind"] == "feed" for job in load_non_browser_jobs(PATH))
    assert not any(feed["name"] == "microsoft_ai_blog" for feed in load_feed_manifest(PATH))
