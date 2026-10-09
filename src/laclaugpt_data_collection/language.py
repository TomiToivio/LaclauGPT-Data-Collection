# -*- coding: utf-8 -*-
"""Language tagging for collected records (issue #238).

Measured 2026-10-09: **713 of 1124** AI26 records carried no language (63.4%),
and the blank was not a random slice — three of the six collecting platforms
never populated the field at all:

    rss      : 535/535 blank
    arxiv    : 179/179 blank
    web      :  14/14  blank
    mastodon :   2/2   blank
    x        : en 51 | fi 4
    bluesky  : en 353 | de 2 | fr 1 | blank 8

The study declares ``languages: [en]`` for elites and ``[en, fi]`` for grassroots
and parliamentary, and §4.2 requires stratification by language. With 63% blank,
neither the declared scope nor the stratification is measurable.

This module supplies the missing tag in the one place every collector passes
through, so a new collector cannot forget it.

**Design rules**

- **Explicit metadata wins.** A feed's ``<language>`` element, an API's ``lang``
  field or a document's declared language is a *statement by the publisher*; a
  detector's guess never overrides it.
- **Detection is a fallback, and it is labelled as such.** A tag derived from
  content is recorded with ``language_source="detected"``, so a later analysis
  can separate what the publisher declared from what we inferred. A guess and a
  declaration must not be indistinguishable in the record.
- **No third-party dependency.** The package's base install is deliberately
  small (httpx/pydantic only), and this runs in the hourly cron; a pure-stdlib
  detector keeps the base install and the hot path unchanged. It is intentionally
  a *coarse script/stopword* detector, not a language-identification model — it
  distinguishes the case that matters here (English vs Finnish, the two the
  study declares) and declines when it is not confident.
- **Declining is a first-class outcome.** ``""`` is returned when there is not
  enough signal, because a wrong tag is worse than a blank one: it would corrupt
  the very stratification this exists to make possible.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

#: Metadata keys, checked in order, that carry an explicit publisher statement.
_EXPLICIT_KEYS: tuple[str, ...] = (
    "language",
    "lang",
    "dc_language",
    "language_guess",
)

#: A BCP-47-ish tag, optionally with a region ("en", "en-US", "fi-FI").
_TAG = re.compile(r"^[A-Za-z]{2,3}(?:[-_][A-Za-z0-9]{2,8})*$")

#: Minimum characters of extractable text before detection is attempted. Below
#: this the signal is too thin and a guess would be noise.
MIN_DETECTION_CHARS = 24


def normalise_tag(value: Any) -> str:
    """Return a lower-cased primary subtag for a declared language, or ''.

    ``"en-US"`` -> ``"en"``; ``"FI"`` -> ``"fi"``. Rejects anything that is not a
    plausible tag, so a stray word in a metadata field cannot become a language.
    """
    if not isinstance(value, str):
        return ""
    candidate = value.strip().lower()
    if not candidate or not _TAG.match(candidate):
        return ""
    return candidate.replace("_", "-").split("-", 1)[0]


def declared_language(*mappings: dict[str, Any] | None) -> str:
    """First explicit, plausible language tag across the given mappings."""
    for mapping in mappings:
        if not isinstance(mapping, dict):
            continue
        for key in _EXPLICIT_KEYS:
            tag = normalise_tag(mapping.get(key))
            if tag:
                return tag
    return ""


#: High-frequency function words. Chosen to be *discriminative between the
#: study's declared languages* (en, fi) rather than to be a general classifier:
#: a token that appears in both lists identifies nothing.
_STOPWORDS: dict[str, frozenset[str]] = {
    "en": frozenset(
        """the of and to in is that for it as was with be by on not he this are or
        from at which but have an they you we his her its their our your has had
        will would can could should there what when where who how why if then than
        more most other some such only own same so too very just also been being""".split()
    ),
    "fi": frozenset(
        """ja on ei se että oli ovat mutta kun myös kuin niin tai jos sen sitä
        hän ne me te he tämä tuo nämä nuo joka mikä missä milloin miten miksi
        kanssa jälkeen ennen mukaan sitten vain vielä aina usein joskus
        suomen suomessa suomalainen yhteiskunta työ tekniikka tekoäly""".split()
    ),
}

_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)

#: Characters that occur in Finnish but not English, a cheap extra signal.
_FINNISH_CHARS = frozenset("äöå")


def detect_language(text: str) -> str:
    """Coarse script/stopword language detection; ``''`` when not confident.

    Returns a primary subtag. Only ``en`` and ``fi`` are produced — the two the
    study declares — because a confident wrong answer is worse than a blank, and
    this detector has no basis for more.
    """
    if not isinstance(text, str) or len(text.strip()) < MIN_DETECTION_CHARS:
        return ""
    lowered = text.casefold()
    words = _WORD.findall(lowered)
    if not words:
        return ""

    scores = {lang: 0 for lang in _STOPWORDS}
    for word in words:
        for lang, lexicon in _STOPWORDS.items():
            if word in lexicon:
                scores[lang] += 1

    # Finnish orthography is highly distinctive; weight it, because a short
    # Finnish snippet often carries no stopwords at all.
    fi_char_hits = sum(1 for ch in lowered if ch in _FINNISH_CHARS)
    scores["fi"] += fi_char_hits

    best = max(scores, key=lambda lang: scores[lang])
    best_score = scores[best]
    runner_up = max((s for lang, s in scores.items() if lang != best), default=0)

    # Require a minimum absolute signal AND a clear margin over the alternative.
    # This is what makes '' (decline) reachable rather than a theoretical branch.
    if best_score < 2:
        return ""
    if best_score <= runner_up:
        return ""
    return best


def resolve_language(
    text: str = "",
    *mappings: dict[str, Any] | None,
) -> tuple[str, str]:
    """Return ``(tag, source)`` where source is ``declared``, ``detected`` or ``''``.

    Explicit metadata always wins; detection is the fallback; a decline is an
    empty tag with an empty source.
    """
    declared = declared_language(*mappings)
    if declared:
        return declared, "declared"
    detected = detect_language(text)
    if detected:
        return detected, "detected"
    return "", ""


def language_metadata(tag: str, source: str) -> dict[str, str]:
    """Provenance fragment for the record, so a guess is never read as a declaration."""
    if not tag:
        return {}
    return {"language": tag, "language_source": source}


def iter_explicit_languages(records: Iterable[dict[str, Any]]) -> dict[str, int]:
    """Count ``language_source`` values across canonical records (audit helper)."""
    counts: dict[str, int] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        source = (record.get("source") or {}).get("raw_metadata", {}) or {}
        value = str(source.get("language_source") or "") or "(none)"
        counts[value] = counts.get(value, 0) + 1
    return counts
