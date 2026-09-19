"""Conservative HTML extraction helpers for the Phase 1 backlog."""

from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from importlib.metadata import PackageNotFoundError, version


def _package_version(name: str) -> str | None:
    try:
        return version(name)
    except PackageNotFoundError:
        return None


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip:
            text = " ".join(data.split())
            if text:
                self.parts.append(text)


@dataclass(frozen=True)
class ExtractionResult:
    text: str
    extractor: str
    extractor_version: str | None


def extract_visible_text(html: str) -> ExtractionResult:
    """Dependency-free baseline used for tests and explicit Phase-1 calls only."""
    parser = _VisibleTextParser()
    parser.feed(html)
    return ExtractionResult(" ".join(parser.parts), "stdlib-html.parser", None)


def extract_with_readability(html: str) -> ExtractionResult:
    """Optional readability-lxml fallback. Raises a clear install hint when absent."""
    try:
        from readability import Document
    except ImportError as exc:
        raise RuntimeError(
            "readability-lxml is optional; install .[phase1-extraction]"
        ) from exc
    summary = Document(html).summary(html_partial=True)
    result = extract_visible_text(summary)
    return ExtractionResult(
        result.text,
        "readability-lxml",
        _package_version("readability-lxml"),
    )
