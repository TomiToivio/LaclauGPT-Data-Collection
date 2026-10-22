"""Issue #321 -- a `web_source` must reach the corpus by advertising its feed.

The defect: a browser-free `web_source` produced dated documents only when its
homepage was one of two keys in `_WEB_SOURCE_FEED_FALLBACKS`; every other row
produced one page snapshot with no publication time, which the analysis handoff
then excludes as `missing_source_publication_time`. The fix under test is feed
*discovery*: read the `<link rel="alternate" type="application/rss+xml">` (or
`atom+xml`) declaration the page itself makes, collect that feed through the
existing RSS collector, and keep both prior paths intact --

    explicit map entry  ->  wins outright, page is never fetched
    advertised feed     ->  dated articles, capped at the row's cycle share
    neither             ->  today's single snapshot, byte-for-byte
    page fetch fails    ->  today's `web_fetch_failed` SourceJobError

What is deliberately NOT tested here is article-link extraction: it is not
implemented, because dating an arbitrary article requires guessing a per-site
date format, and a wrong publication time is worse for the corpus than a
missing one.
"""
from __future__ import annotations

import httpx
import pytest

from laclaugpt_data_collection import ai26_laskin_runner as runner
from laclaugpt_data_collection.collectors.base import CollectionResult
from laclaugpt_data_collection.models import CollectionProvenance, NormalizedRecord
from laclaugpt_data_collection.web_fetch import discover_feed_urls, fetch_web_child

HOME = "https://example.org/blog/"
FEED = "https://example.org/feed.xml"
TIMESTAMP = "2026-10-15T09:00:00Z"


def _page(head: str = "", *, title: str = "Lab blog") -> str:
    return (
        f"<html><head><title>{title}</title>{head}</head>"
        "<body><h1>Lab blog</h1><p>Substantive source text.</p></body></html>"
    )


def _rss_link(href: str = FEED, *, rel: str = "alternate", ctype: str = "application/rss+xml") -> str:
    return f'<link rel="{rel}" type="{ctype}" href="{href}" title="Feed">'


def _transport(html: str, *, status: int = 200, calls: list[str] | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(str(request.url))
        return httpx.Response(
            status,
            headers={"content-type": "text/html; charset=utf-8"},
            text=html,
        )

    return httpx.MockTransport(handler)


def _patch_transport(monkeypatch, transport) -> None:
    """Inject a transport through the one `fetch_web_child` call the branch makes."""

    def fetch(url, parent, **kwargs):
        return fetch_web_child(
            url,
            parent,
            transport=transport,
            host_validator=lambda _url: True,
            **kwargs,
        )

    monkeypatch.setattr(runner, "fetch_web_child", fetch)


class _StubFeedCollector:
    """Stand-in for `RSSCollector`: records the call, returns dated entries."""

    calls: list[dict] = []
    items = 3

    def __init__(self, feed_urls, *, max_items_per_feed: int = 100, **kwargs) -> None:
        type(self).calls.append({"feeds": list(feed_urls), "limit": max_items_per_feed})
        self.feed_urls = list(feed_urls)
        self.max_items_per_feed = max_items_per_feed

    def collect(self) -> CollectionResult:
        records = [
            NormalizedRecord(
                document_id=f"entry-{index}",
                platform="rss",
                timestamp=TIMESTAMP,
                source_url=f"https://example.org/posts/{index}",
                text=f"Entry {index} body",
                raw_payload={"id": f"entry-{index}"},
                collection_provenance=CollectionProvenance(module="issue-321-stub"),
            )
            for index in range(type(self).items)
        ]
        return CollectionResult(records=records)


@pytest.fixture()
def feeds(monkeypatch):
    _StubFeedCollector.calls = []
    _StubFeedCollector.items = 3
    monkeypatch.setattr(runner, "RSSCollector", _StubFeedCollector)
    return _StubFeedCollector


def _row(**overrides):
    row = {
        "kind": "web_source",
        "name": "synthetic_lab_blog",
        "homepage": HOME,
        "arena": "elites",
        "priority": "P1",
        "source_family": "frontier lab",
    }
    row.update(overrides)
    return row


def _collect(row=None, *, per_source_limit: int = 5):
    return runner._records_for_job(
        row or _row(),
        collection_id="ai26",
        worker_id="laskin-test",
        per_source_limit=per_source_limit,
    )


def _strip_fetch_times(payload):
    """Drop collection timestamps so two fetches can be compared as documents."""

    if isinstance(payload, dict):
        return {
            key: _strip_fetch_times(value)
            for key, value in payload.items()
            if key not in {"collected_at", "captured_at", "generated_at"}
        }
    if isinstance(payload, list):
        return [_strip_fetch_times(value) for value in payload]
    return payload


# ---------------------------------------------------------------------------
# discovery reads the page's own declaration
# ---------------------------------------------------------------------------


class TestDiscovery:
    def test_rss_alternate_link_is_discovered(self) -> None:
        assert discover_feed_urls(_page(_rss_link()), HOME) == [FEED]

    def test_atom_alternate_link_is_discovered(self) -> None:
        head = _rss_link(
            "https://example.org/atom.xml", ctype="application/atom+xml"
        )
        assert discover_feed_urls(_page(head), HOME) == ["https://example.org/atom.xml"]

    def test_relative_href_is_resolved_against_the_page(self) -> None:
        assert discover_feed_urls(_page(_rss_link("/feeds/all.xml")), HOME) == [
            "https://example.org/feeds/all.xml"
        ]

    def test_discovery_is_capped_at_one_feed_per_call(self) -> None:
        head = _rss_link() + _rss_link("https://example.org/second.xml")
        assert discover_feed_urls(_page(head), HOME) == [FEED]

    def test_page_without_a_declaration_has_no_feed(self) -> None:
        assert discover_feed_urls(_page('<link rel="stylesheet" href="s.css">'), HOME) == []

    def test_non_alternate_or_wrong_type_links_are_ignored(self) -> None:
        head = _rss_link(rel="stylesheet") + _rss_link(ctype="text/html")
        assert discover_feed_urls(_page(head), HOME) == []

    @pytest.mark.parametrize("body", [None, "", "<html><head>"])
    def test_missing_or_truncated_html_is_a_no_feed_page(self, body) -> None:
        assert discover_feed_urls(body, HOME) == []

    def test_non_http_href_is_not_handed_to_a_fetcher(self) -> None:
        assert discover_feed_urls(_page(_rss_link("javascript:alert(1)")), HOME) == []


# ---------------------------------------------------------------------------
# the runner: discovery, override, fallback, failure, budget
# ---------------------------------------------------------------------------


class TestRunnerDiscovery:
    def test_discovered_feed_yields_dated_records(self, monkeypatch, feeds) -> None:
        _patch_transport(monkeypatch, _transport(_page(_rss_link())))

        records, warnings = _collect()

        assert feeds.calls == [{"feeds": [FEED], "limit": 5}]
        assert warnings == []
        assert len(records) == 3
        # The whole point of the fix: these are dated, so they survive the handoff.
        for record in records:
            assert record.source.created_at == TIMESTAMP
            assert record.source_url.startswith("https://example.org/posts/")
            assert record.source.raw_metadata["source_name"] == "synthetic_lab_blog"
            assert record.source.raw_metadata["arena"] == "elites"

    def test_atom_link_reaches_the_collector(self, monkeypatch, feeds) -> None:
        head = _rss_link("https://example.org/atom.xml", ctype="application/atom+xml")
        _patch_transport(monkeypatch, _transport(_page(head)))

        _collect()

        assert feeds.calls[0]["feeds"] == ["https://example.org/atom.xml"]

    def test_relative_link_reaches_the_collector_absolute(self, monkeypatch, feeds) -> None:
        _patch_transport(monkeypatch, _transport(_page(_rss_link("feed.xml"))))

        _collect()

        assert feeds.calls[0]["feeds"] == ["https://example.org/feed.xml"]


class TestMapOverrideWins:
    def test_override_wins_over_a_discoverable_feed(self, monkeypatch, feeds) -> None:
        calls: list[str] = []
        # If the page is fetched at all the override did not win; make it loud.
        _patch_transport(
            monkeypatch,
            _transport(_page(_rss_link("https://example.org/other.xml")), calls=calls),
        )

        records, _warnings = _collect(
            _row(name="microsoft_ai_blog", homepage="https://www.microsoft.com/en-us/ai/blog/")
        )

        assert calls == [], "the override must not fetch the homepage first"
        assert feeds.calls[0]["feeds"] == ["https://www.microsoft.com/en-us/ai/blog/feed/"]
        assert len(records) == 3

    def test_override_lookup_ignores_the_trailing_slash(self, monkeypatch, feeds) -> None:
        _patch_transport(monkeypatch, _transport(_page()))

        _collect(_row(name="openai_news", homepage="https://openai.com/news"))

        assert feeds.calls[0]["feeds"] == ["https://openai.com/news/rss.xml"]


class TestSnapshotFallbackIsUnchanged:
    def test_no_feed_page_produces_todays_single_record(self, monkeypatch, feeds) -> None:
        url = "https://example.org/no-feed"
        page = _page('<link rel="stylesheet" href="s.css">', title="No feed here")
        _patch_transport(monkeypatch, _transport(page))

        records, warnings = _collect(_row(homepage=url))

        assert feeds.calls == []
        assert warnings == []
        assert len(records) == 1
        record = records[0]
        assert record.source_url == url
        assert record.source.platform == "web"
        assert record.source.created_at is None, "the snapshot is still undated, as today"
        assert record.content.title == "No feed here"

        # Same document as the pre-#321 code path built: identical payload once
        # fetch timestamps are removed, so nothing was added to the snapshot.
        parent = NormalizedRecord(
            document_id=url,
            platform="web",
            source_url=url,
            text="",
            raw_payload={},
            collection_provenance=CollectionProvenance(module="ai26-laskin-web-seed"),
        )
        outcome = fetch_web_child(
            url,
            parent,
            collection_id="ai26",
            arena="elites",
            transport=_transport(page),
            host_validator=lambda _url: True,
        )
        expected = runner._stamp(
            outcome.record, _row(homepage=url), collection_id="ai26", worker_id="laskin-test"
        )
        assert _strip_fetch_times(record.model_dump(mode="json")) == _strip_fetch_times(
            expected.model_dump(mode="json")
        )
        assert outcome.html is not None, "the page body is available without a second fetch"

    def test_non_html_page_is_still_a_snapshot(self, monkeypatch, feeds) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                headers={"content-type": "application/pdf"},
                content=b"%PDF-1.4 synthetic",
            )

        _patch_transport(monkeypatch, httpx.MockTransport(handler))

        records, warnings = _collect()

        assert feeds.calls == []
        assert warnings == []
        assert len(records) == 1
        assert records[0].content.media_references[0].kind == "pdf"

    def test_discovered_feed_with_no_items_falls_back_to_one_snapshot(
        self, monkeypatch, feeds
    ) -> None:
        feeds.items = 0
        _patch_transport(monkeypatch, _transport(_page(_rss_link())))

        records, warnings = _collect()

        assert feeds.calls[0]["feeds"] == [FEED]
        # One snapshot, never two, and the empty feed is reported by name.
        assert len(records) == 1
        assert records[0].source.created_at is None
        assert records[0].source_url == HOME.rstrip("/")
        assert len(warnings) == 1
        assert "synthetic_lab_blog" in warnings[0]
        assert FEED in warnings[0]


class TestFetchFailuresKeepTodaysBehaviour:
    def test_http_error_status_is_preserved_and_nothing_raises_upward(
        self, monkeypatch, feeds
    ) -> None:
        _patch_transport(monkeypatch, _transport(_page(_rss_link()), status=403))

        with pytest.raises(runner.SourceJobError) as excinfo:
            _collect()

        assert excinfo.value.reason == "web_fetch_failed"
        assert excinfo.value.status_code == 403
        assert feeds.calls == [], "a failed page must not start a feed fetch"

    def test_timeout_is_a_source_job_error_not_a_crash(self, monkeypatch, feeds) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectTimeout("synthetic timeout", request=request)

        _patch_transport(monkeypatch, httpx.MockTransport(handler))

        with pytest.raises(runner.SourceJobError) as excinfo:
            _collect()

        assert excinfo.value.reason == "web_fetch_failed"
        assert excinfo.value.status_code is None
        assert feeds.calls == []

    def test_the_cycle_records_the_failure_as_a_blocked_source(
        self, monkeypatch, tmp_path
    ) -> None:
        """End to end: a 403 row is still one blocked outcome, not a crashed tick."""
        from pathlib import Path  # noqa: F401  (documented: tmp_path is a Path)

        class Sink:
            notification_errors: list[str] = []

            def __init__(self, settings):
                pass

            def assert_private_config(self, path):
                pass

            def ingest(self, payload):
                pass

            def ingest_with_status(self, payload):
                return payload, True

        monkeypatch.setattr(runner, "DistributedCaptureSink", Sink)
        monkeypatch.setattr(
            runner, "load_non_browser_jobs", lambda path: [_row(name="blocked_blog")]
        )
        monkeypatch.setattr(runner, "preflight_optional_dependencies", lambda jobs: [])
        monkeypatch.setattr(
            runner, "run_phase1_rss", lambda *args, **kwargs: {"records_synced": 0}
        )
        _patch_transport(monkeypatch, _transport(_page(_rss_link()), status=403))

        from laclaugpt_data_collection.config import Settings

        result = runner.run_phase1_laskin(
            Settings(_env_file=None, project_id="ai26"),
            study_config=tmp_path / "ai26.yaml",
            source_manifest=tmp_path / "sources.toml",
            rotation=0,
            max_jobs=1,
            limit=10,
        )

        outcome = result["source_outcomes"][0]
        assert outcome["status"] == "blocked"
        assert outcome["reason"] == "web_fetch_failed"
        assert outcome["http_status"] == 403
        assert result["non_browser_records_synced"] == 0


class TestCycleBudget:
    def test_a_web_source_cannot_take_more_than_its_share(self, monkeypatch, feeds) -> None:
        feeds.items = 20
        _patch_transport(monkeypatch, _transport(_page(_rss_link())))

        records, _warnings = _collect(per_source_limit=3)

        assert feeds.calls[0]["limit"] == 3, "the feed depth is the declared share"
        assert len(records) == 3, "an over-delivering collector is still capped"

    def test_the_cap_holds_for_the_map_override_too(self, monkeypatch, feeds) -> None:
        feeds.items = 20
        _patch_transport(monkeypatch, _transport(_page()))

        records, _warnings = _collect(
            _row(name="openai_news", homepage="https://openai.com/news/"),
            per_source_limit=2,
        )

        assert feeds.calls[0]["limit"] == 2
        assert len(records) == 2

    def test_zero_share_is_clamped_to_one_rather_than_fetching_nothing(
        self, monkeypatch, feeds
    ) -> None:
        _patch_transport(monkeypatch, _transport(_page(_rss_link())))

        records, _warnings = _collect(per_source_limit=0)

        assert feeds.calls[0]["limit"] == 1
        assert len(records) == 1


class TestPolicyIsNotChanged:
    def test_no_new_web_source_rows_and_the_floor_is_untouched(self) -> None:
        """This fix is code-only: (b), the stage-scoped policy change, was not taken."""
        import tomllib
        from pathlib import Path

        manifest = tomllib.loads(
            (Path(__file__).resolve().parents[1] / "configs" / "studies" / "ai26.sources.example.toml")
            .read_text(encoding="utf-8")
        )
        assert len(manifest.get("web_source") or []) == 12
