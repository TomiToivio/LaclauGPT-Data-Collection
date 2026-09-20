from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from laclaugpt_data_collection.handoff import build_handoff
from laclaugpt_data_collection.plugins import CollectionContext, CollectionRunner, default_registry
from laclaugpt_data_collection.storage.local import SQLiteRecordStore


class _Entry(dict):
    def __getattr__(self, name: str):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


@pytest.mark.parametrize(
    ("feed_url", "entry"),
    [
        (
            "https://example.invalid/rss.xml",
            _Entry(
                id="rss-item-1",
                link="https://EXAMPLE.invalid/articles/1/?utm_source=fixture#fragment",
                title="Synthetic RSS item",
                summary="RSS fixture body",
                published="Sat, 19 Sep 2026 10:00:00 GMT",
                author="Fixture Author",
                format="rss",
            ),
        ),
        (
            "https://example.invalid/atom.xml",
            _Entry(
                id="tag:example.invalid,2026:atom-2",
                link="https://example.invalid/articles/2?fbclid=fixture",
                title="Synthetic Atom item",
                summary="Atom fixture body",
                updated="2026-09-19T10:05:00Z",
                author="Fixture Author",
                format="atom",
            ),
        ),
    ],
)
def test_phase1_rss_plugin_vertical_slice_is_canonical_and_idempotent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    feed_url: str,
    entry: _Entry,
) -> None:
    def parse(url: str):
        assert url == feed_url
        return SimpleNamespace(entries=[entry])

    monkeypatch.setitem(sys.modules, "feedparser", SimpleNamespace(parse=parse))

    registry = default_registry()
    store = SQLiteRecordStore(tmp_path / "phase1-rss.sqlite3")
    runner = CollectionRunner(registry, store)
    context = CollectionContext(
        config={"feed_urls": [feed_url], "max_items_per_feed": 10},
        project_id="fixture-project",
        collection_id="RSS26",
        arena="public-feed",
        run_id="phase1-rss-run",
        privacy={"access": "research-only", "publish_raw": False},
    )

    first = runner.run("rss", context)
    second = runner.run("rss", context)

    assert first.records_seen == 1
    assert first.records_written == 1
    assert first.duplicates_skipped == 0
    assert second.records_seen == 1
    assert second.records_written == 0
    assert second.duplicates_skipped == 1

    records = store.all()
    assert len(records) == 1
    record = records[0]

    expected_url = (
        "https://example.invalid/articles/1"
        if entry["format"] == "rss"
        else "https://example.invalid/articles/2"
    )
    assert record.source_url == expected_url
    assert record.source_native_ids["document_id"]
    assert record.source.platform == "rss"
    assert record.source.source_type == "rss"
    assert record.source.collection_method == "rss"
    assert record.content.text == f'{entry["title"]}\n\n{entry["summary"]}'

    assert record.raw_capture.preserved
    assert record.raw_capture.content_type == "application/feed+json"
    assert record.raw_capture.payload["id"] == entry["id"]
    assert record.raw_capture.payload["format"] == entry["format"]

    assert record.provenance[0].module == "rss-feedparser"
    assert record.provenance[-1].module == "collection-plugin:rss"
    assert record.provenance[-1].metadata["collection_id"] == "RSS26"
    assert record.provenance[-1].metadata["privacy"]["publish_raw"] is False

    restored = store.get(expected_url)
    assert restored is not None
    assert restored.model_dump(mode="json") == record.model_dump(mode="json")

    handoff = build_handoff(restored.model_dump(mode="json"), project_id="fixture-project")
    assert handoff["contract_version"] == "1.0"
    assert handoff["source_url"] == expected_url
    assert handoff["collection_id"] == "RSS26"
    assert handoff["arena"] == "public-feed"
    assert handoff["status"] == "ready"
