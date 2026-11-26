"""Exercise the real collector and handoff with local parser fixtures."""
import sys
from types import SimpleNamespace

from scripts.probe_ai26_parliamentary_sources import TARGETS, probe


def test_probe_real_normalization_and_handoff(monkeypatch):
    entry = SimpleNamespace(
        title="AI legislation", link="https://example.org/bill",
        summary="Public legislative proposal concerning artificial intelligence.",
        published="Wed, 25 Nov 2026 10:00:00 GMT", language="en",
    )
    parsed = SimpleNamespace(entries=[entry], bozo=False)
    monkeypatch.setitem(sys.modules, "feedparser", SimpleNamespace(parse=lambda _: parsed))
    report = probe([
        {"name": name, "feed_url": "https://example.org/feed", "arena": "parliamentary"}
        for name in TARGETS
    ])
    assert all(row["passed"] for row in report.values()), report
    assert all(row["usable_dated_text"] == 1 for row in report.values())


def test_probe_failures_and_missing_manifest(monkeypatch):
    monkeypatch.setitem(sys.modules, "feedparser", SimpleNamespace(
        parse=lambda _: SimpleNamespace(entries=[], status=503),
    ))
    report = probe([{"name": TARGETS[0], "feed_url": "https://example.org/feed"}])
    assert not report[TARGETS[0]]["passed"]
    assert "HTTP failure (503)" in report[TARGETS[0]]["warnings"][0]
    assert not report[TARGETS[1]]["passed"]
