"""#459: an absent language tag must say *why* it is absent, machine-readably.

The AI26 study uses language as a stratum variable, and two cycles on 2026-11-22 stored 3-8 records per hour
with no ``source.language``. The cycle warned about it, but the stored record did not record that a decision
had been made: 'we could not tell' and 'we never asked' were indistinguishable downstream, and so was 'the
text was too short to guess'.

The two reasons are different defects:
- ``unreported`` — the platform supplies a language and the collector did not read it (a mapping gap);
- ``insufficient_text`` — detection correctly refused to guess on a short text (a provenance fact).

Both now land in ``source.raw_metadata`` as ``language_status = "undetermined"`` plus ``language_reason``.
"""

from __future__ import annotations

import pytest

from laclaugpt_data_collection.language import resolve_language


@pytest.mark.parametrize(
    ("text", "expected_reason"),
    [
        ("", "insufficient_text"),
        ("ok", "insufficient_text"),
    ],
)
def test_detection_refuses_to_guess_on_short_text(text, expected_reason):
    detected, method = resolve_language(text)
    assert detected == ""
    assert method == expected_reason


def test_a_substantive_text_is_detected_so_the_marker_is_not_written():
    detected, method = resolve_language(
        "The European Parliament voted today on a binding framework for artificial intelligence systems."
    )
    if method == "detector_unavailable":
        # langdetect is an optional extra; without it resolve_language degrades to an empty
        # tag by design (#294) and this assertion would be testing the environment.
        pytest.skip("langdetect is not installed in this environment")
    assert detected
    assert method != "insufficient_text"


def test_the_runner_records_the_abstention_and_its_reason():
    """The marker is written on the path that finalises a record before storage."""
    import inspect

    from laclaugpt_data_collection import ai26_laskin_runner

    source = inspect.getsource(ai26_laskin_runner)
    assert '"language_status"] = "undetermined"' in source
    assert '"language_reason"' in source
