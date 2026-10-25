"""Pure, network-free contracts for the guarded AI26 #336 arena backfill."""
import pytest

from scripts.backfill_ai26_x_arenas import (
    declared_x_handles,
    resolve_record,
    x_handle_from_profile,
)


def test_declared_handles_and_case_normalization():
    groups = {"groups": [
        {"id": "labs", "arena": "elites", "accounts": {"x": ["OpenAI", "@AnthropicAI"]}},
        {"id": "workers", "arena": "grassroots", "accounts": {"x": ["UnionAI"]}},
    ]}
    mapping = declared_x_handles(groups)
    assert mapping["openai"] == ("elites", "labs")
    assert mapping["anthropicai"] == ("elites", "labs")
    assert mapping["unionai"] == ("grassroots", "workers")


def test_conflicting_declarations_fail_closed():
    with pytest.raises(ValueError, match="ambiguous"):
        declared_x_handles({"groups": [
            {"id": "a", "arena": "elites", "accounts": {"x": ["OpenAI"]}},
            {"id": "b", "arena": "grassroots", "accounts": {"x": ["openai"]}},
        ]})


@pytest.mark.parametrize("url,handle", [
    ("https://x.com/OpenAI", "openai"),
    ("https://x.com/OpenAI/status/123", "openai"),
    ("https://twitter.com/OpenAI", "openai"),
    ("@OpenAI", "openai"),
    ("https://other.example/OpenAI", ""),
    ("https://x.com/home", ""),
    ("https://x.com/OpenAI/following", ""),
])
def test_profile_identity_is_strict(url, handle):
    assert x_handle_from_profile(url) == handle


def test_only_known_x_and_consistent_authors_repair():
    mapping = {"openai": ("elites", "labs")}
    row = {"source": {"platform": "x", "author": "OpenAI",
                      "raw_metadata": {"source_platform_url": "https://x.com/OpenAI"}}}
    assert resolve_record(row, mapping) == ("elites", "labs")
    assert resolve_record({"source": {**row["source"], "platform": "web"}}, mapping) is None
    assert resolve_record({"source": {**row["source"], "author": "Other"}}, mapping) == ("elites", "labs")
    assert resolve_record({"source": {**row["source"], "author": "https://x.com/UnionAI"}}, mapping) is None


def test_unknown_capture_handle_is_not_inferred():
    assert resolve_record({"source": {"platform": "x", "author": "stranger"}},
                          {"openai": ("elites", "labs")}) is None
