"""Safety properties of the issue #250 read-only candidate classifier."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "preflight", Path(__file__).resolve().parents[1] / "scripts/report_ai26_legacy_provenance.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


MANIFEST = {
    "feed": [
        {"name": "example", "homepage": "https://example.org/blog",
         "arena": "elites"},
        {"name": "another", "homepage": "https://other.org",
         "arena": "grassroots"},
    ],
    "web_source": [{"name": "public", "url": "https://agency.gov/ai",
                    "arena": "parliamentary"}],
}


def record(platform, url):
    return {"_id": "id1", "source": {"platform": platform, "url": url,
                                     "author": "Someone"}}


def test_unique_origin_matches_only_configured_arena():
    result = module.candidates(record("rss", "https://example.org/blog/a"), MANIFEST)
    assert result["status"] == "unique"
    assert result["matches"][0]["arena"] == "elites"


def test_author_does_not_infer_arena():
    result = module.candidates(record("rss", "https://unknown.org/story"), MANIFEST)
    assert result["status"] == "unmatched"
    assert result["matches"] == []


def test_prefix_collision_is_not_origin_match():
    assert module.candidates(record("rss", "https://example.org/blogger/a"), MANIFEST)["status"] == "unmatched"


def test_cross_platform_source_is_not_a_match():
    assert module.candidates(record("web", "https://example.org/blog/a"), MANIFEST)["status"] == "unmatched"


def test_two_configured_sources_same_origin_are_ambiguous():
    manifest = {"feed": [MANIFEST["feed"][0],
                         {"name": "duplicate", "homepage": "https://example.org/blog",
                          "arena": "grassroots"}]}
    assert module.candidates(record("rss", "https://example.org/blog/a"), manifest)["status"] == "ambiguous"


def test_missing_explicit_arena_is_not_backfilled():
    manifest = {"feed": [{"name": "missing", "homepage": "https://example.org/blog"}]}
    assert module.candidates(record("rss", "https://example.org/blog/a"), manifest)["status"] == "unmatched"
