"""Regression coverage for the unlabelled parliamentary arena (#294).

Two different causes were behind "0 of 296 parliamentary rows carry
`source.language`":

1. a collector gap -- `bluesky._map_post` read only the optional `record.langs`
   field and never asked the shared resolver, so a post without `langs` (the
   Valtioneuvosto account omits it) stayed untagged even though rss and arxiv
   resolve a language for the same arena;
2. a silent degradation -- `resolve_language` returns an empty tag when the
   optional `langdetect` detector is missing, and nothing in the cycle said so.
   Live evidence: 175 stored records carry `language_method=detector_unavailable`.

These tests pin the wiring and the visibility. They deliberately do not touch
which sources the parliamentary arena samples, nor the arena's `languages:`
declaration.
"""
from __future__ import annotations

import sys
import types

import pytest

from laclaugpt_data_collection.collectors.bluesky import _map_post
from laclaugpt_data_collection.language import (
    resolve_language,
    unlabelled_language_counts,
    unlabelled_language_warning,
)
from laclaugpt_data_collection.models import CollectionProvenance, NormalizedRecord

# Titles taken verbatim from the issue (Valtioneuvosto / parliamentary arena).
FINNISH_TITLES = [
    "Ympäristöministeriö pyytää lausuntoja rakennusten vesilaitteistojen rakennustuotteita",
    "Valtioneuvoston tutkimustoiminnan vuoden 2027 ensimmäinen tarjouskilpailu avattu",
    "Puolustusministeri Häkkinen työvierailulle Uuteen-Seelantiin, Australiaan ja Japaniin",
]


def _post(text: str, *, langs: list[str] | None = None) -> dict:
    record: dict = {"text": text, "createdAt": "2026-10-09T12:06:30Z"}
    if langs is not None:
        record["langs"] = langs
    return {
        "uri": "at://did:plc:valtioneuvosto/app.bsky.feed.post/3mxgwqw7myy2j",
        "cid": "bafy-fixture",
        "author": {"handle": "valtioneuvosto.fi", "displayName": "Valtioneuvosto | Statsrådet"},
        "record": record,
        "indexedAt": "2026-10-09T12:06:31.157Z",
        "likeCount": 0,
        "replyCount": 0,
        "repostCount": 0,
        "quoteCount": 0,
    }


@pytest.fixture
def finnish_detector(monkeypatch):
    """Install a stand-in `langdetect` so the detection path is exercised.

    This is a wiring fixture, not a detection-quality claim: it answers `fi` for
    text containing Finnish letters and `en` otherwise, so a collector that
    consults the shared resolver gets a tag and a collector that does not gets
    nothing.
    """

    class DetectorFactory:
        seed = 0

    class LangDetectException(Exception):
        pass

    class Candidate:
        def __init__(self, lang: str, prob: float) -> None:
            self.lang = lang
            self.prob = prob

    finnish = set("äöåÄÖÅ")

    def detect_langs(text: str):
        return [Candidate("fi", 0.99)] if finnish & set(text) else [Candidate("en", 0.99)]

    module = types.ModuleType("langdetect")
    module.DetectorFactory = DetectorFactory
    module.LangDetectException = LangDetectException
    module.detect_langs = detect_langs
    monkeypatch.setitem(sys.modules, "langdetect", module)
    return module


def test_bluesky_post_without_declared_langs_asks_the_shared_resolver(finnish_detector):
    """The collector gap: `langs` is optional, and its absence is not "unknown"."""
    record = _map_post(_post(FINNISH_TITLES[0]))

    assert record is not None
    assert record.source.language == "fi"
    assert record.provenance[-1].metadata["language_method"] == "detected_langdetect"


def test_bluesky_declared_langs_still_win_over_detection(finnish_detector):
    record = _map_post(_post("Valtioneuvosto tiedottaa", langs=["sv"]))

    assert record is not None
    assert record.source.language == "sv"
    assert record.provenance[-1].metadata["language_method"] == "source_metadata"


def test_bluesky_does_not_invent_a_language_without_a_detector(monkeypatch):
    """No detector, no guess: the tag stays empty and says why."""
    monkeypatch.setitem(sys.modules, "langdetect", None)
    record = _map_post(_post(FINNISH_TITLES[0]))

    assert record is not None
    assert record.source.language == ""
    assert record.provenance[-1].metadata["language_method"] == "detector_unavailable"


@pytest.mark.parametrize("title", FINNISH_TITLES)
def test_real_finnish_titles_are_detected_as_finnish(title):
    """With the declared detector installed, the real Valtioneuvosto rows label fi."""
    pytest.importorskip("langdetect")
    language, method = resolve_language(title)
    assert language == "fi", f"{title!r} should be Finnish"
    assert method == "detected_langdetect"


def _untagged(platform: str, source_name: str, method: str) -> NormalizedRecord:
    record = NormalizedRecord(
        source_url=f"https://example.invalid/{source_name}/{platform}",
        platform=platform,
        text="text without a language tag",
        timestamp="2026-10-15T00:00:00Z",
        raw_payload={},
        collection_provenance=CollectionProvenance(
            module="test", metadata={"language_method": method}
        ),
    )
    record.source.raw_metadata["source_name"] = source_name
    return record


def test_language_warning_names_sources_and_the_missing_detector():
    records = [
        _untagged("rss", "tech_policy_press", "detector_unavailable"),
        _untagged("rss", "tech_policy_press", "detector_unavailable"),
        _untagged("bluesky", "Finnish Government (Valtioneuvosto)", "insufficient_text"),
    ]

    assert unlabelled_language_counts(records) == {
        "tech_policy_press": {"detector_unavailable": 2},
        "Finnish Government (Valtioneuvosto)": {"insufficient_text": 1},
    }
    warning = unlabelled_language_warning(records)
    assert warning is not None
    assert "3 record(s) stored without source.language" in warning
    assert "tech_policy_press=2" in warning
    assert "detector_unavailable=2" in warning
    assert "langdetect" in warning, "the missing detector is the actionable part"


def test_language_warning_is_silent_when_every_record_is_tagged():
    record = _untagged("rss", "eu_digital_strategy", "source_metadata")
    record.source.language = "en"

    assert unlabelled_language_counts([record]) == {}
    assert unlabelled_language_warning([record]) is None


def test_rss_cycle_reports_unlabelled_records_without_failing(monkeypatch):
    from laclaugpt_data_collection import factory, server_runner
    from laclaugpt_data_collection.collectors.base import CollectionResult
    from laclaugpt_data_collection.config import Settings

    class Store:
        def __init__(self):
            self.ids = []

        def upsert(self, record):
            self.ids.append(record.source_url)
            return True

    class RSS:
        def __init__(self, urls, *, max_items_per_feed, source_name):
            self.source_name = source_name

        def collect(self):
            result = CollectionResult(requests_seen=1, bodies_seen=1, raw_items_seen=1)
            result.records = [_untagged("rss", self.source_name, "detector_unavailable")]
            return result

    store = Store()
    monkeypatch.setattr(server_runner, "load_feed_manifest", lambda _p: [
        {"name": "tech_policy_press", "feed_url": "https://example.invalid/feed"}
    ])
    monkeypatch.setattr(server_runner, "RSSCollector", RSS)
    monkeypatch.setattr(factory, "build_record_store", lambda _settings: store)

    settings = Settings(
        _env_file=None,
        project_id="ai26",
        record_backend="csv",
        mongodb_uri="",
        object_backend="filesystem",
        cache_backend="memory",
        distributed_config_backend="local",
        messaging_backend="none",
        task_queue_backend="direct",
    )
    summary = server_runner.run_phase1_rss(
        settings,
        study_config="unused.yaml",
        source_manifest="synthetic.toml",
        collection_id="ai26",
        rotation=0,
    )

    assert summary["status"] == "ok", "a missing language tag must not fail the cycle"
    assert summary["records_synced"] == 1
    assert any("stored without source.language" in w for w in summary["warnings"])
    assert any("tech_policy_press=1" in w for w in summary["warnings"])
