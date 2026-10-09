"""Language tagging with provenance; never assert a guess as source metadata."""
from __future__ import annotations

import re

_VALID = re.compile(r"^[a-z]{2,3}(?:-[a-z]{2,8})?$")


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
        return "", "detector_unavailable"
    DetectorFactory.seed = 0
    try:
        candidates = detect_langs(text[:10000])
    except LangDetectException:
        return "", "undetectable"
    if candidates and candidates[0].prob >= 0.90:
        return candidates[0].lang, "detected_langdetect"
    return "", "low_confidence"
