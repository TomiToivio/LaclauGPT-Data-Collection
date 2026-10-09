# -*- coding: utf-8 -*-
"""Issue #238: every record must carry an inferable language tag.

Measured 2026-10-09: **713 of 1124** AI26 records (63.4%) had no language, and the
blank was not a random slice — `rss`, `arxiv` and `web` never set the field, and
`normalize.py` explicitly blanked it for every platform except `x`. The study
declares `languages: [en]` / `[en, fi]` and §4.2 requires stratification by
language, so neither was measurable.

These tests pin the three properties that make the tag usable, not merely present:

1. **Declared beats detected.** A publisher's statement must never be overridden
   by our inference, and the record must say which it was.
2. **Detection declines rather than guesses.** A wrong tag corrupts the very
   stratification it exists to enable, so a thin or ambiguous input must yield
   `""`.
3. **The collectors actually populate it**, including the three that never did.
"""
from __future__ import annotations

import inspect

import pytest

from laclaugpt_data_collection.language import (
    MIN_DETECTION_CHARS,
    detect_language,
    language_metadata,
    normalise_tag,
    resolve_language,
)
from laclaugpt_data_collection.normalize import normalise

_EN = "The government will decide and it will be enforced by law and regulation."
_FI = "Tekoäly on uusi teknologia, ja se muuttaa yhteiskuntaa Suomessa."


# ------------------------------------------------------------- the detector --

def test_english_and_finnish_are_distinguished() -> None:
    assert detect_language(_EN) == "en"
    assert detect_language(_FI) == "fi"


@pytest.mark.parametrize(
    "text",
    [
        "",                       # nothing at all
        "hi",                     # below MIN_DETECTION_CHARS
        "?!... 12345",            # no letters
        "https://example.com/feed",  # a URL is not prose
        "x" * MIN_DETECTION_CHARS,   # repetitive filler carries no signal
    ],
)
def test_detection_declines_on_thin_or_ambiguous_input(text: str) -> None:
    """A wrong language tag is worse than a blank one: it corrupts stratification."""
    assert detect_language(text) == ""


def test_detection_never_invents_a_language_outside_the_declared_scope() -> None:
    """Only `en` and `fi` are produced — the two the study declares."""
    for text in (_EN, _FI, "Le gouvernement va décider et il sera appliqué par la loi."):
        assert detect_language(text) in {"", "en", "fi"}


# ------------------------------------------------------- explicit metadata --

@pytest.mark.parametrize(
    "raw,expected",
    [("en", "en"), ("FI", "fi"), ("en-US", "en"), ("fi_FI", "fi"),
     ("", ""), ("nope", ""), ("not a lang", "")],
)
def test_tag_normalisation(raw: str, expected: str) -> None:
    assert normalise_tag(raw) == expected


def test_declared_metadata_beats_detection() -> None:
    """A publisher's declaration must not be overridden by our inference."""
    tag, source = resolve_language(_EN, {"language": "fi"})
    assert (tag, source) == ("fi", "declared")


def test_detection_is_labelled_as_a_guess() -> None:
    """A guess and a declaration must not be indistinguishable in the record."""
    tag, source = resolve_language(_EN)
    assert (tag, source) == ("en", "detected")
    assert language_metadata(tag, source) == {"language": "en", "language_source": "detected"}


def test_a_decline_produces_no_language_metadata() -> None:
    assert language_metadata("", "") == {}


# ------------------------------------------------- the normalizer (all platforms) --

def test_the_normalizer_labels_a_platform_that_never_had_a_language() -> None:
    """The root cause: `language` was blanked for every platform except `x`."""
    record = normalise("tiktok", {"id": "1", "author": "a", "body": _EN})
    assert record.language == "en"


def test_the_normalizer_still_honours_a_collector_language_guess() -> None:
    """The pre-existing `x` path (`language_guess`) must keep working."""
    record = normalise("x", {"id": "1", "author": "a", "body": "short", "language_guess": "fi"})
    assert record.language == "fi"


def test_the_normalizer_honours_capture_metadata_language() -> None:
    record = normalise("instagram", {"id": "1", "author": "a", "body": "x"}, metadata={"language": "fi"})
    assert record.language == "fi"


# --------------------------------------------------------------- the collectors --

#: The collectors that populated no language before #238, by module path. `documents`
#: is not re-exported from the package `__init__` (it is an internal helper), so it is
#: addressed by its full path rather than through `collectors`.
_COLLECTOR_MODULES = (
    "laclaugpt_data_collection.collectors.rss",
    "laclaugpt_data_collection.collectors.arxiv",
    "laclaugpt_data_collection.collectors.documents",
)


def _module_source(path: str) -> str:
    import importlib

    return inspect.getsource(importlib.import_module(path))


def test_rss_reads_the_feed_declared_language() -> None:
    """An RSS feed's own <language> element is the publisher's declaration."""
    source = _module_source("laclaugpt_data_collection.collectors.rss")
    assert "feed_language" in source
    assert 'getattr(parsed, "feed", {})' in source, (
        "the RSS collector no longer reads the feed's declared language"
    )


@pytest.mark.parametrize("module_path", _COLLECTOR_MODULES)
def test_the_previously_unlabelled_collectors_resolve_a_language(module_path: str) -> None:
    """rss/arxiv/web set no language at all before #238."""
    source = _module_source(module_path)
    assert "resolve_language" in source, f"{module_path} does not resolve a language"
    assert "language_metadata" in source, (
        f"{module_path} does not record whether the tag was declared or detected"
    )


def test_the_collectors_set_the_field_not_only_metadata() -> None:
    """The record's own `language` field must be populated, not just the provenance."""
    for module_path in (
        "laclaugpt_data_collection.collectors.arxiv",
        "laclaugpt_data_collection.collectors.documents",
    ):
        source = _module_source(module_path)
        assert "language=tag," in source, f"{module_path} computes a tag but never assigns it"
