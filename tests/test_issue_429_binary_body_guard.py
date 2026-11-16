"""Issue #429: a compressed or binary body must never be stored as text.

The failure this pins is silent. `errors="replace"` turns undecodable bytes into a perfectly valid
`str`, so a gzip body served under `content-type: text/html` becomes a `ready` record whose `text` is
43.8 % U+FFFD — and the analysis stage codes it as discourse. One real AI26 record did exactly that.
"""
from __future__ import annotations

import gzip

import pytest

from laclaugpt_data_collection.web_fetch import (
    decode_text_body,
    text_is_plausible,
)


class TestDecodeTextBody:
    def test_a_compressed_body_is_decompressed_before_decoding(self):
        payload = "<html><body><p>Puolueet väittelevät.</p></body></html>".encode("utf-8")
        text, diagnostics = decode_text_body(gzip.compress(payload))
        assert "Puolueet" in text
        assert diagnostics["decompressed_from"] == "gzip"
        assert diagnostics["replacement_share"] == 0.0

    def test_undecodable_bytes_are_counted_not_hidden(self):
        # The real record's shape: a stray high byte every couple of characters.
        body = b"\x8b" * 60 + b"text" + b"\x8b" * 60
        text, diagnostics = decode_text_body(body)
        assert diagnostics["replacement_characters"] > 0
        assert diagnostics["replacement_share"] > 0.10
        plausible, reason = text_is_plausible(diagnostics)
        assert not plausible and "replacement_share" in reason

    def test_a_control_character_run_is_refused(self):
        body = b"text" + b"\x01\x02\x03\x04\x05\x06\x07" * 10
        _, diagnostics = decode_text_body(body)
        plausible, reason = text_is_plausible(diagnostics)
        assert not plausible and "control_characters" in reason


class TestLegitimatePagesStillPass:
    """A naive "non-ASCII means binary" rule would delete every Finnish and Japanese record."""

    @pytest.mark.parametrize("sample", [
        "Puolueet väittelevät maahanmuutosta ja taloudesta. Äänestäjät ovat tyytymättömiä.",
        "政党は移民政策について議論している。有権者は不満を持っている。",
        "Partidele dezbat politica de migrație; alegătorii sunt nemulțumiți.",
    ])
    def test_non_ascii_text_is_text(self, sample):
        text, diagnostics = decode_text_body(sample.encode("utf-8"))
        plausible, reason = text_is_plausible(diagnostics)
        assert plausible, reason
        assert text == sample

    def test_newlines_and_tabs_are_not_control_characters(self):
        body = ("line one\nline two\r\n\tindented\n" * 40).encode("utf-8")
        _, diagnostics = decode_text_body(body)
        assert diagnostics["control_characters"] == 0
        assert text_is_plausible(diagnostics)[0]


class TestTheFetcherRefusesInsteadOfStoring:
    """The guard has to reach the record, not just exist in a helper."""

    def _record(self):
        from laclaugpt_data_collection.models import CanonicalRecord, ContentSection, SourceSection

        return CanonicalRecord(
            source_url="https://example.org/parent",
            source=SourceSection(platform="x", collector="test"),
            content=ContentSection(text="Parent post linking an article."),
        )

    def _fetch(self, body: bytes, content_type: str = "text/html"):
        import httpx

        from laclaugpt_data_collection.web_fetch import fetch_web_child

        transport = httpx.MockTransport(
            lambda request: httpx.Response(200, content=body,
                                           headers={"content-type": content_type})
        )
        return fetch_web_child("https://example.org/article", self._record(),
                               transport=transport, host_validator=lambda host: True)

    def test_a_compressed_body_is_rejected_with_a_reason(self):
        outcome = self._fetch(gzip.compress(b"\x8b\x8b\x8b binary-ish payload"))
        assert outcome.record is None
        assert outcome.error.startswith("binary_body_rejected")

    def test_mojibake_under_a_text_label_is_rejected(self):
        outcome = self._fetch(b"\x8b" * 400)
        assert outcome.record is None
        assert "replacement_share" in outcome.error

    def test_a_normal_page_is_stored_with_its_decode_diagnostics(self):
        outcome = self._fetch("<html><head><title>Otsikko</title></head><body><p>Artikkeli.</p>"
                              "</body></html>".encode("utf-8"))
        assert outcome.record is not None
        assert "Artikkeli" in outcome.record.content.text
        metadata = outcome.record.raw_capture.metadata
        assert metadata["text_decode"]["replacement_share"] == 0.0
        assert metadata["text_decode"]["characters"] > 0


class TestQuarantineRule:
    """The repair path applies the fetcher's rule to text already in the store."""

    def _diagnose(self, text):
        import importlib.util
        from pathlib import Path

        spec = importlib.util.spec_from_file_location(
            "quarantine_implausible_text",
            Path(__file__).resolve().parents[1] / "scripts" / "quarantine_implausible_text.py",
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.diagnose(text)

    def test_the_real_record_shape_is_caught(self):
        # 43.8 % U+FFFD plus control characters: the one record #429 is about.
        text = ("\ufffd" * 3940) + ("\x01" * 896) + ("ok " * 1000)
        plausible, reason, diagnostics = self._diagnose(text)
        assert not plausible
        assert diagnostics["replacement_share"] > 0.10

    def test_a_normal_multilingual_text_is_not_quarantined(self):
        plausible, reason, diagnostics = self._diagnose(
            "Puolueet väittelevät. 政党は議論する。 Partidele dezbat."
        )
        assert plausible and reason == ""
        assert diagnostics["replacement_characters"] == 0

    def test_empty_text_is_not_a_defect(self):
        plausible, _, diagnostics = self._diagnose("")
        assert plausible and diagnostics["characters"] == 0

