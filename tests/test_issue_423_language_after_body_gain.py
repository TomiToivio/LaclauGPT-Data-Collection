"""A record that gains an article body must also gain its language label (#423).

#416 gave headline-only RSS records a body but left ``source.language`` blank, because the label had
been resolved while the record still held a 62-character title. Measured on Laskin 2026-11-15: 52
``tech_policy_press`` records moved from "title, no language" to "full article body, still no
language", and the arena-by-language cells stayed computed over indeterminate cases while the
evidence to resolve them sat in the same document.

What these tests pin:

* the label is resolved from the **body**, not from the headline that produced a blank the first time;
* a record that already carries a language is never relabelled — a platform value or a declared row
  language outranks a detection (#294 ordering);
* a resolution failure (missing detector, low confidence, short text) still applies the body patch
  without a language: the enrichment must not be lost because the label could not be guessed;
* the summary reports what was labelled, so a cycle that enriches but cannot label says so.

langdetect is stubbed exactly as ``tests/test_issue_294_language_labels.py`` stubs it, so this suite
needs no detector model and its assertions are deterministic.
"""
from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from laclaugpt_data_collection.rss_body_enrichment import (
    EnrichmentResult,
    build_patch,
    enrich_record,
    resolved_language_for_body,
    summarise,
)

ENGLISH_HEADLINE = "Finland publishes its AI policy guidelines for public administration"
FINNISH_BODY = (
    "Valtioneuvosto julkaisi tänään esityksen tekoälyn käytön linjauksista julkishallinnossa. "
    "Esityksen mukaan virastojen on arvioitava järjestelmiensä vaikutukset ennen käyttöönottoa, "
    "ja kansalaisille on kerrottava avoimesti, milloin päätöksenteossa käytetään tekoälyä. "
    "Ministeri korosti, että luottamus syntyy läpinäkyvyydestä ja siitä, että viranomaiset "
    "vastaavat järjestelmiensä toiminnasta myös silloin, kun ne epäonnistuvat. "
)
ARTICLE_HTML = (
    "<html><body><nav>Etusivu | Yhteystiedot</nav><article><p>" + FINNISH_BODY + "</p></article></body></html>"
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
        return [self._candidate]


@pytest.fixture
def fake_langdetect(monkeypatch: pytest.MonkeyPatch):
    def install(language: str = "fi", probability: float = 0.99) -> _FakeLangdetect:
        module = _FakeLangdetect(language, probability)
        monkeypatch.setitem(sys.modules, "langdetect", module)
        return module

    return install


def record(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "_id": "rec-423",
        "project_id": "ai26",
        "source_url": "https://valtioneuvosto.fi/-/tekoaly-linjaukset",
        "handoff": {"status": "ready", "published_at": "2026-11-10T00:00:00+00:00"},
        "source": {"platform": "rss", "raw_metadata": {"source_name": "valtioneuvosto"}},
        "content": {"text": ENGLISH_HEADLINE},
        "human_readable": {"summary": "old", "generated_at": "2026-11-10T00:00:00+00:00"},
        "provenance": [{"module": "rss", "transformations": ["parse-feed"]}],
    }
    base.update(overrides)
    return base


# ------------------------------------------------------------------ the resolver


def test_language_is_resolved_from_the_body_not_the_headline(fake_langdetect):
    fake_langdetect("fi")
    tag, method = resolved_language_for_body(record(), FINNISH_BODY)
    assert (tag, method) == ("fi", "detected_langdetect")


def test_an_existing_language_is_never_replaced(fake_langdetect):
    fake_langdetect("fi")  # detection would say Finnish
    labelled = record(source={"platform": "rss", "language": "en"})
    assert resolved_language_for_body(labelled, FINNISH_BODY) == ("", "")


def test_short_body_stays_unknown():
    # No stub installed on purpose: the text floor is checked before the detector is imported.
    assert resolved_language_for_body(record(), "Tekoäly") == ("", "insufficient_text")


def test_missing_detector_stays_unknown(monkeypatch: pytest.MonkeyPatch):
    """A venv without langdetect must lose the label, not the enrichment."""
    monkeypatch.setitem(sys.modules, "langdetect", None)
    assert resolved_language_for_body(record(), FINNISH_BODY) == ("", "detector_unavailable")


def test_low_confidence_stays_unknown(fake_langdetect):
    fake_langdetect("fi", probability=0.55)
    assert resolved_language_for_body(record(), FINNISH_BODY) == ("", "low_confidence")


# ------------------------------------------------------------------ the patch


def test_patch_fills_the_blank_label_and_records_the_method():
    patch = build_patch(
        record(),
        body_text=FINNISH_BODY,
        final_url="https://valtioneuvosto.fi/-/tekoaly-linjaukset",
        fetched_at="2026-11-15T12:00:00+00:00",
        language="fi",
        language_method="detected_langdetect",
    )
    assert patch["source.language"] == "fi"
    assert patch["source.raw_metadata.language_method"] == "detected_langdetect"
    # The previous value was blank; keep it recorded so the write stays reversible (#361).
    assert patch["source.raw_metadata.language_backfill"] == ""
    assert patch["provenance"][-1]["metadata"]["language_from_body"] == "detected_langdetect"


def test_patch_without_a_language_touches_no_language_field():
    patch = build_patch(
        record(),
        body_text=FINNISH_BODY,
        final_url="https://valtioneuvosto.fi/-/tekoaly-linjaukset",
        fetched_at="2026-11-15T12:00:00+00:00",
    )
    assert [key for key in patch if "language" in key] == []
    assert patch["provenance"][-1]["metadata"]["language_from_body"] == ""


# ------------------------------------------------------------------ the whole call


def test_enrich_record_labels_the_body_it_stored(fake_langdetect):
    fake_langdetect("fi")
    result, patch = enrich_record(
        record(),
        fetch=lambda url: (url, ARTICLE_HTML),
        now=lambda: "2026-11-15T12:00:00+00:00",
    )
    assert result.status == "enriched"
    assert (result.language, result.language_method) == ("fi", "detected_langdetect")
    assert patch is not None
    assert patch["source.language"] == "fi"
    assert len(patch["content.text"]) >= len(FINNISH_BODY)
    assert result.as_dict()["language"] == "fi"


def test_a_labelled_record_keeps_its_own_language(fake_langdetect):
    fake_langdetect("fi")
    declared = record(source={"platform": "rss", "language": "en"})
    result, patch = enrich_record(declared, fetch=lambda url: (url, ARTICLE_HTML))
    assert result.status == "enriched"
    assert result.language == ""
    assert patch is not None
    assert "source.language" not in patch


def test_a_failed_detector_still_applies_the_body(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setitem(sys.modules, "langdetect", None)
    result, patch = enrich_record(record(), fetch=lambda url: (url, ARTICLE_HTML))
    assert result.status == "enriched"
    assert result.language == ""
    assert patch is not None
    assert "source.language" not in patch
    # The provenance records the attempt's outcome, not only its success: "detector_unavailable" here
    # is why a record can hold an article body and still carry no label, which #294 showed must be
    # visible rather than silent.
    assert patch["provenance"][-1]["metadata"]["language_from_body"] == "detector_unavailable"


# ------------------------------------------------------------------ reporting


def test_summary_counts_what_was_labelled():
    summary = summarise(
        [
            EnrichmentResult("u1", "enriched", 60, 1200, language="fi", language_method="detected_langdetect"),
            EnrichmentResult("u2", "enriched", 60, 1200, language="en", language_method="detected_langdetect"),
            EnrichmentResult("u3", "enriched", 60, 1200),
            EnrichmentResult("u4", "skipped", 60, 90),
        ]
    )
    assert summary["languages_resolved"] == 2
    assert summary["language_methods"] == {"detected_langdetect": 2}
    assert summary["counts"] == {"enriched": 3, "skipped": 1}
    assert [row["language"] for row in summary["enriched"]] == ["fi", "en", ""]
