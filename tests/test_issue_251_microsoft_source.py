"""Issue #251 — Microsoft must be present in the AI26 elites sampling frame.

The `elites` arena declares `frontier-lab and industry discourse` as its first
sampling focus, and the manifest carried first-party blog rows for OpenAI, Anthropic,
Google DeepMind and Meta but nothing for Microsoft. This guards the row and, more
importantly, guards that the row can actually *collect* on the browser-free Laskin
stage: a `web_source` there only collects through the feed-fallback map, so a row
without an entry is a declared-but-impossible stratum (the #249 defect class).
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "configs" / "studies" / "ai26.sources.example.toml"
RUNNER = ROOT / "src" / "laclaugpt_data_collection" / "ai26_laskin_runner.py"

#: Verified live 2026-10-11: HTTP 200, 10 items, newest 2026-10-05 (inside the window).
MICROSOFT_FEED = "https://www.microsoft.com/en-us/ai/blog/feed/"


def _rows(text: str) -> list[dict[str, str]]:
    """Minimal row reader: enough for the flat ``[[kind]]`` blocks this issue touches."""
    rows: list[dict[str, str]] = []
    cur: dict[str, str] | None = None
    for line in text.splitlines():
        m = re.match(r"^\[\[(\w+)\]\]", line.strip())
        if m:
            cur = {"kind": m.group(1)}
            rows.append(cur)
        elif cur is not None and "=" in line and not line.strip().startswith("#"):
            key, _, value = line.partition("=")
            cur[key.strip()] = value.strip().strip('"')
    return rows


def _plan() -> list[dict[str, str]]:
    return _rows(PLAN.read_text(encoding="utf-8"))


def _fallback_block() -> str:
    text = RUNNER.read_text(encoding="utf-8")
    return text.split("_WEB_SOURCE_FEED_FALLBACKS = {", 1)[1].split("}", 1)[0]


def test_microsoft_has_a_row_in_the_ai26_sampling_plan() -> None:
    rows = [
        r
        for r in _plan()
        if "microsoft" in (r.get("name", "") + r.get("homepage", "")).lower()
    ]
    assert rows, "no Microsoft row in the AI26 sampling plan"
    row = rows[0]
    assert row["kind"] == "web_source"
    assert row["arena"] == "elites"
    assert row["homepage"].startswith("https://www.microsoft.com/")


def test_the_microsoft_row_names_the_verified_feed_in_the_runner() -> None:
    assert MICROSOFT_FEED in RUNNER.read_text(encoding="utf-8"), (
        "the verified Microsoft feed is not wired into the runner"
    )


def test_the_fallback_key_matches_the_homepage_the_runner_looks_up() -> None:
    """The runner rstrips '/', so the map key must be the homepage without it."""
    row = next(r for r in _plan() if r.get("name") == "microsoft_ai_blog")
    key = row["homepage"].rstrip("/")
    assert f'"{key}"' in _fallback_block(), (
        "no fallback keyed on the row's homepage, so the row would seed a URL and "
        "collect nothing on the browser-free stage"
    )


def test_the_fallback_points_at_the_feed_url_verified_for_this_issue() -> None:
    block = _fallback_block()
    key = "https://www.microsoft.com/en-us/ai/blog"
    assert f'"{key}": "{MICROSOFT_FEED}"' in block


def test_microsoft_is_excluded_from_the_rows_with_no_collection_path() -> None:
    """#251's actual acceptance: the row must not be a declared-but-impossible stratum.

    Side observation worth recording (tracked on #249, not asserted here because most
    `web_source` rows are deliberate browser-stage seeds): only `openai_news` and now
    `microsoft_ai_blog` have a feed fallback, so on the browser-free stage the other
    lab blog rows seed a URL and collect nothing. Pinning that set would fail on every
    legitimate new browser-stage seed, so it is recorded rather than frozen.
    """
    fallbacks = _fallback_block()
    row = next(r for r in _plan() if r.get("name") == "microsoft_ai_blog")
    assert row["homepage"].rstrip("/") in fallbacks
