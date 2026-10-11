"""Regression checks for explicit AI26 sampling decisions (#249, #251)."""
from pathlib import Path
import tomllib

from laclaugpt_data_collection.ai26_laskin_runner import load_non_browser_jobs

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
    rows = [row for row in data["feed"] if row["name"] == "microsoft_ai_blog"]
    assert len(rows) == 1
    assert rows[0]["feed_url"] == "https://www.microsoft.com/en-us/ai/blog/feed/"
    assert rows[0]["arena"] == "elites"
    assert rows[0]["active"] is True
    assert any(job["kind"] == "feed" and job["name"] == "microsoft_ai_blog"
               for job in load_non_browser_jobs(PATH))
