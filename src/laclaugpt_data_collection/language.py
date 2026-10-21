"""Language tagging with provenance; never assert a guess as source metadata."""
from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

_VALID = re.compile(r"^[a-z]{2,3}(?:-[a-z]{2,8})?$")

_DETECTOR_HINT = (
    "the optional langdetect detector is not installed in this venv "
    "(pip install '.[feeds]')"
)
_NO_DETECTOR = "detector_unavailable"


def resolve_language(text: str, *, declared: str = "") -> tuple[str, str]:
    """Prefer explicit source metadata; use optional detection for substantive text.

    Unknown stays unknown rather than contaminating language-stratified research.
    """
    tag = declared.strip().lower().replace("_", "-")
    if _VALID.fullmatch(tag):
        return tag.split("-")[0], "source_metadata"
    if len(text.strip()) < 80:
        return "", "insufficient_text"
    try:
        from langdetect import DetectorFactory, LangDetectException, detect_langs
    except ImportError:
        return "", _NO_DETECTOR
    DetectorFactory.seed = 0
    try:
        candidates = detect_langs(text[:10000])
    except LangDetectException:
        return "", "undetectable"
    if candidates and candidates[0].prob >= 0.90:
        return candidates[0].lang, "detected_langdetect"
    return "", "low_confidence"


def _record_parts(record: Any) -> tuple[Mapping[str, Any], Mapping[str, Any], list[Any]]:
    """Return ``(source, content, provenance)`` from a model or a plain mapping."""
    if isinstance(record, Mapping):
        source = record.get("source")
        content = record.get("content")
        provenance = record.get("provenance")
    else:
        source = getattr(record, "source", None)
        content = getattr(record, "content", None)
        provenance = getattr(record, "provenance", None)
    return _as_mapping(source), _as_mapping(content), list(provenance or [])


def _as_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    dumped = getattr(value, "model_dump", None)
    if not callable(dumped):
        return {}
    payload = dumped()
    return payload if isinstance(payload, Mapping) else {}


def _language_method(provenance: list[Any]) -> str:
    if not provenance:
        return "unreported"
    last = _as_mapping(provenance[-1])
    metadata = _as_mapping(last.get("metadata"))
    return str(metadata.get("language_method") or "unreported")


def unlabelled_language_counts(records: Iterable[Any]) -> dict[str, dict[str, int]]:
    """Count records stored with no language tag, per source and per reason.

    #294: 0 of 296 parliamentary rows carried ``source.language`` while the arena
    declares ``languages: [en, fi]``. Some of that was a collector gap (bluesky
    never asked the shared resolver); the rest was ``detector_unavailable`` --
    `resolve_language` degrades to an empty tag when `langdetect` is missing, and
    nothing said so. Losing a tag silently is what makes a language-stratified
    sample impossible to demonstrate, so the cycle now reports it.
    """
    counts: dict[str, dict[str, int]] = {}
    for record in records:
        source, content, provenance = _record_parts(record)
        if str(source.get("language") or content.get("language") or "").strip():
            continue
        metadata = _as_mapping(source.get("raw_metadata"))
        name = str(metadata.get("source_name") or source.get("platform") or "unnamed")
        reason = _language_method(provenance)
        by_reason = counts.setdefault(name, {})
        by_reason[reason] = by_reason.get(reason, 0) + 1
    return counts


def unlabelled_language_warning(records: Iterable[Any]) -> str | None:
    """Return one counted, source-naming warning for records with no language tag."""
    counts = unlabelled_language_counts(records)
    if not counts:
        return None
    total = sum(sum(reasons.values()) for reasons in counts.values())
    sources = ", ".join(
        f"{name}={sum(reasons.values())}"
        for name, reasons in sorted(
            counts.items(), key=lambda item: (-sum(item[1].values()), item[0])
        )
    )
    reasons: dict[str, int] = {}
    for by_reason in counts.values():
        for reason, count in by_reason.items():
            reasons[reason] = reasons.get(reason, 0) + count
    reason_text = ", ".join(
        f"{reason}={count}"
        for reason, count in sorted(reasons.items(), key=lambda item: (-item[1], item[0]))
    )
    message = (
        f"{total} record(s) stored without source.language: {sources}; "
        f"reason: {reason_text}"
    )
    if _NO_DETECTOR in reasons:
        message = f"{message} -- {_DETECTOR_HINT}"
    return message
