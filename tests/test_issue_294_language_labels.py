"""Issue #294 -- the parliamentary arena could not be reported on by language.

Two things are pinned here, both of them label *plumbing* rather than a sampling
change:

1. every collector resolves a language the same way, and a source-declared value
   always beats a guess (Bluesky used the platform's ``langs`` only, so the 48
   Valtioneuvosto posts that declare none stayed blank even though their text is
   plainly Finnish);
2. a source row may declare its language once, in the manifest, and that value
   fills only an EMPTY record language -- a per-item observation is never
   overwritten by an assertion about the source;
3. the corpus audit reports the language cross-tab PER ARENA, so an arena whose
   whole stratum is unlabelled is named instead of being diluted by the arenas
   that do label.

The decisions the issue leaves to the owner (which document types the
parliamentary arena should sample, and whether to declare languages on the
existing rows) are deliberately NOT encoded here.
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

from laclaugpt_data_collection import ai26_laskin_runner as runner
from laclaugpt_data_collection import server_runner
from laclaugpt_data_collection.collectors.bluesky import _map_post
from laclaugpt_data_collection.corpus_audit import audit_records, audit_summary
from laclaugpt_data_collection.language import apply_declared_language
from laclaugpt_data_collection.models import CollectionProvenance, NormalizedRecord

FINNISH_POST = (
    "Valtioneuvoston tutkimustoiminnan vuoden 2027 ensimmäinen tarjouskilpailu "
    "avattu: haussa yhteiskunnallisesti vaikuttavaa tutkimusta tekoälystä ja "
    "julkisen hallinnon digitalisaatiosta."
)


def _post(**record_fields) -> dict:
    return {
        "uri": "at://did:plc:example/app.bsky.feed.post/3kabc",
        "cid": "bafyexample",
        "author": {"handle": "valtioneuvosto.fi", "displayName": "Valtioneuvosto"},
        "record": {
            "text": FINNISH_POST,
            "createdAt": "2026-10-19T08:00:00.000Z",
            **record_fields,
        },
        "indexedAt": "2026-10-19T08:00:05.000Z",
        "likeCount": 3,
    }


def _record(url: str = "https://example.org/a", language: str = "") -> NormalizedRecord:
    return NormalizedRecord(
        source_url=url,
        platform="rss",
        text="sample",
        timestamp="2026-10-19T00:00:00Z",
        language=language,
        raw_payload={},
        collection_provenance=CollectionProvenance(module="test"),
    )


class _FakeLangdetect(types.ModuleType):
    """Deterministic stand-in for langdetect, so this suite needs no model."""

    class LangDetectException(Exception):
        pass

    class DetectorFactory:  # noqa: D401 - langdetect's own surface
        seed = 0

    def __init__(self, language: str = "fi", probability: float = 0.99) -> None:
        super().__init__("langdetect")
        self._candidate = types.SimpleNamespace(lang=language, prob=probability)

    def detect_langs(self, text: str):  # noqa: ARG002 - signature parity
        candidate = self._candidate
        return [candidate]


@pytest.fixture
def fake_langdetect(monkeypatch):
    def install(language: str = "fi", probability: float = 0.99) -> _FakeLangdetect:
        module = _FakeLangdetect(language, probability)
        monkeypatch.setitem(sys.modules, "langdetect", module)
        return module

    return install


class TestBlueskyLanguagePath:
    def test_a_declared_platform_language_wins_over_detection(self, fake_langdetect):
        fake_langdetect("en")  # detection would say English
        record = _map_post(_post(langs=["fi"]))
        assert record is not None
        assert record.source.language == "fi"
        assert record.provenance[-1].metadata["language_method"] == "source_metadata"

    def test_a_post_without_langs_falls_back_to_detection(self, fake_langdetect):
        fake_langdetect("fi")
        record = _map_post(_post())  # no `langs`: the Valtioneuvosto case
        assert record is not None
        assert record.source.language == "fi"
        assert record.provenance[-1].metadata["language_method"] == "detected_langdetect"

    def test_low_confidence_detection_leaves_the_label_blank(self, fake_langdetect):
        fake_langdetect("fi", probability=0.55)
        record = _map_post(_post())
        assert record is not None
        assert record.source.language == ""
        assert record.provenance[-1].metadata["language_method"] == "low_confidence"

    def test_a_missing_detector_does_not_invent_a_label(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "langdetect", None)
        record = _map_post(_post())
        assert record is not None
        assert record.source.language == ""
        assert record.provenance[-1].metadata["language_method"] in {
            "detector_unavailable",
            "insufficient_text",
        }

    def test_short_posts_are_not_guessed_even_with_a_detector(self, fake_langdetect):
        fake_langdetect("fi")
        post = _post()
        post["record"]["text"] = "Tiedote."
        record = _map_post(post)
        assert record is not None
        assert record.source.language == ""
        assert record.provenance[-1].metadata["language_method"] == "insufficient_text"


class TestManifestDeclaredLanguage:
    def test_a_row_declaration_fills_a_blank_record(self) -> None:
        record = _record()
        method = apply_declared_language(record, "fi-FI")
        assert method == "source_metadata"
        assert record.source.language == "fi"

    def test_a_platform_value_is_never_overwritten(self) -> None:
        record = _record(language="en")
        assert apply_declared_language(record, "fi") == ""
        assert record.source.language == "en"

    def test_an_invalid_tag_changes_nothing(self) -> None:
        record = _record()
        assert apply_declared_language(record, "not a language") == ""
        assert record.source.language == ""

    def test_no_declaration_changes_nothing(self) -> None:
        record = _record()
        assert apply_declared_language(record, "") == ""
        assert record.source.language == ""

    def test_the_rss_stamper_records_how_the_label_was_produced(self) -> None:
        record = _record()
        stamped = server_runner._stamp_source_metadata(
            record,
            {"name": "valtioneuvosto", "feed_url": "https://example.invalid/feed", "language": "fi"},
            collection_id="ai26",
            worker_id="test",
        )
        assert stamped.source.language == "fi"
        metadata = stamped.provenance[-1].metadata
        assert metadata["language_method"] == "source_metadata"
        assert metadata["language_declared_by"] == "manifest_row"

    def test_the_laskin_stamper_records_the_same_provenance(self) -> None:
        record = _record()
        stamped = runner._stamp(
            record,
            {"name": "valtioneuvosto", "kind": "bluesky_account", "language": "fi"},
            collection_id="ai26",
            worker_id="test",
        )
        assert stamped.source.language == "fi"
        metadata = stamped.provenance[-1].metadata
        assert metadata["language_method"] == "source_metadata"
        assert metadata["language_declared_by"] == "manifest_row"

    def test_a_feed_level_language_still_beats_the_row_declaration(self) -> None:
        from laclaugpt_data_collection.collectors.rss import _entry_to_record

        entry = types.SimpleNamespace(
            link="https://example.org/a",
            title="Otsikko",
            summary="Lyhyt",
            published="",
        )
        record = _entry_to_record("https://example.invalid/feed", entry, feed_language="sv")
        assert record is not None
        assert record.source.language == "sv"
        assert apply_declared_language(record, "fi") == ""
        assert record.source.language == "sv"


def _canonical(arena: str, language: str, url: str) -> dict:
    return {
        "project_id": "ai26",
        "arena": arena,
        "source": {
            "source_url": url,
            "platform": "rss",
            "language": language,
            "raw_metadata": {"source_name": url},
        },
    }


class TestArenaLanguageCrossTab:
    def test_an_unlabelled_arena_is_visible_even_when_the_store_is_labelled(self) -> None:
        records = [
            _canonical("parliamentary", "", "https://example.org/p1"),
            _canonical("parliamentary", "", "https://example.org/p2"),
            _canonical("elites", "en", "https://example.org/e1"),
            _canonical("grassroots", "fi", "https://example.org/g1"),
        ]
        report = audit_records(
            records, arena_languages={"parliamentary": ["en", "fi"], "elites": ["en"]}
        )
        parliamentary = report["by_arena_language"]["arenas"]["parliamentary"]
        assert parliamentary["records"] == 2
        assert parliamentary["labelled"] == 0
        assert parliamentary["unlabelled"] == 2
        assert parliamentary["records_in_declared_scope"] == 0
        assert parliamentary["declared_scope_checked"] is True
        # the store-wide total would have said "2 without language" and looked small
        assert report["by_language"]["unlabelled"] == 2

    def test_the_declared_scope_is_counted_per_arena(self) -> None:
        records = [
            _canonical("elites", "en", "https://example.org/e1"),
            _canonical("elites", "de", "https://example.org/e2"),
        ]
        report = audit_records(records, arena_languages={"elites": ["en"]})
        elites = report["by_arena_language"]["arenas"]["elites"]
        assert elites["records_in_declared_scope"] == 1
        assert elites["counts"] == {"de": 1, "en": 1}

    def test_without_a_declared_scope_the_check_is_not_reported_as_passed(self) -> None:
        report = audit_records([_canonical("parliamentary", "", "https://example.org/p1")])
        assert report["by_arena_language"]["declared_scope_checked"] is False
        assert (
            report["by_arena_language"]["arenas"]["parliamentary"]["records_in_declared_scope"]
            is None
        )

    def test_the_summary_names_the_silent_arena(self) -> None:
        report = audit_records(
            [_canonical("parliamentary", "", "https://example.org/p1")],
            arena_languages={"parliamentary": ["en", "fi"]},
        )
        summary = audit_summary(report)
        assert "parliamentary arena has 0 labelled records" in summary

    def test_a_labelled_arena_is_not_named(self) -> None:
        report = audit_records(
            [_canonical("parliamentary", "fi", "https://example.org/p1")],
            arena_languages={"parliamentary": ["en", "fi"]},
        )
        assert "0 labelled records" not in audit_summary(report)


class TestCliWiring:
    def test_the_study_config_supplies_the_arena_language_scope(
        self, tmp_path: Path, capsys
    ) -> None:
        from laclaugpt_data_collection.cli import _corpus_audit

        records = tmp_path / "records.jsonl"
        records.write_text(
            json.dumps(_canonical("parliamentary", "", "https://example.org/p1")) + "\n",
            encoding="utf-8",
        )
        study = tmp_path / "study.yaml"
        study.write_text(
            "arenas:\n"
            "  parliamentary:\n"
            "    languages: [en, fi]\n"
            "  elites:\n"
            "    languages: [en]\n",
            encoding="utf-8",
        )
        args = types.SimpleNamespace(
            records=str(records),
            mongodb_uri="",
            mongodb_database="",
            mongodb_collection="",
            project="",
            limit=10,
            top_n=3,
            publication_floor="",
            configured_sources="",
            study_config=str(study),
        )
        assert _corpus_audit(args) == 0
        report = json.loads(capsys.readouterr().out)
        parliamentary = report["by_arena_language"]["arenas"]["parliamentary"]
        assert parliamentary["declared_languages"] == ["en", "fi"]
        assert parliamentary["labelled"] == 0
