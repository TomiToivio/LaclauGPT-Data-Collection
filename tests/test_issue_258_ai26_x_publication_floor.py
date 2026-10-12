"""Issue #258: the publication floor must actually apply to browser-captured X records.

`tests/test_realtime.py` already pins `analysis_eligibility()` against synthetic dicts,
including the two branches that matter here — `before_publication_date_floor` and
`missing_source_publication_time`. What was NOT covered is the integration between the
Firefox capture path and that policy.

The AI26 study declares both a floor and a missing-time rule:

    collection_policy:
      timestamp_basis: source_publication_time
      missing_publication_time: retain_but_mark_unresolved
      source_publication_time_required_for_analysis: true

and `realtime.source_publication_time()` states its own contract explicitly:

    Collection/fetch timestamps are intentionally excluded: missing source time must
    remain explicit rather than being silently replaced by collection time.

These tests check that the browser capture path honours that contract. A capture
envelope carries no source publication time at all — `browser/firefox/capture.js` only
ever sends `captured_at: new Date().toISOString()` — so a record whose real publication
date is unknown must stay explicitly unknown, not inherit the clock of the capture.
"""

from __future__ import annotations

from laclaugpt_data_collection.capture import BrowserCapture
from laclaugpt_data_collection.capture_server import capture_to_record
from laclaugpt_data_collection.realtime import (
    RealtimePolicy,
    analysis_eligibility,
    source_publication_time,
)

CAPTURED_AT = "2026-10-12T07:30:00+00:00"
POST_URL = "https://x.com/OpenAI/status/1900000000000000000"


def _capture() -> BrowserCapture:
    return BrowserCapture(
        source_url=POST_URL,
        platform="x",
        captured_at=CAPTURED_AT,
        post_id="1900000000000000000",
        author="OpenAI",
        text="Synthetic research fixture for the AI26 X capture path.",
    )


def _canonical_record(*, published_at: str | None) -> dict:
    """Canonical AI26 X record as produced by a capture.

    `published_at=None` models what the extension can actually send today: no source
    publication time. A non-None value models a capture that did supply one.
    """
    data = capture_to_record(_capture()).model_dump(mode="json")
    if published_at is not None:
        data["source"]["created_at"] = published_at
    return data


def test_capture_clock_is_not_substituted_for_source_publication_time() -> None:
    """The core contract: capture time must never become the publication time."""
    data = _canonical_record(published_at=None)
    assert source_publication_time(data) is None, (
        "the browser capture path substituted the collection clock for the source "
        "publication time, so `missing_source_publication_time` can never fire for "
        "a captured X record"
    )
    assert data["source"].get("created_at") in (None, "")


def test_unknown_publication_time_stays_unresolved_and_ineligible() -> None:
    """`missing_publication_time: retain_but_mark_unresolved` + the floor's precondition."""
    data = _canonical_record(published_at=None)
    eligible, reason = analysis_eligibility(data, RealtimePolicy.ai26())
    assert (eligible, reason) == (False, "missing_source_publication_time")


def test_capture_time_is_preserved_as_collection_time() -> None:
    """Fixing the publication time must not lose the collection time that is real."""
    data = _canonical_record(published_at=None)
    assert data["provenance"][0]["captured_at"] == CAPTURED_AT
    assert data["raw_capture"]["payload"]["captured_at"] == CAPTURED_AT
    assert data["source"].get("collected_at") == CAPTURED_AT


def test_pre_floor_x_record_is_rejected_after_canonicalisation() -> None:
    data = _canonical_record(published_at="2026-08-31T23:59:59+00:00")
    assert analysis_eligibility(data, RealtimePolicy.ai26()) == (
        False,
        "before_publication_date_floor",
    )


def test_x_record_on_the_floor_boundary_is_eligible() -> None:
    data = _canonical_record(published_at="2026-09-01T00:00:00+00:00")
    assert analysis_eligibility(data, RealtimePolicy.ai26()) == (True, "eligible")


def test_within_window_x_record_is_eligible() -> None:
    data = _canonical_record(published_at="2026-09-18T10:00:00+00:00")
    assert analysis_eligibility(data, RealtimePolicy.ai26()) == (True, "eligible")


def test_publication_floor_is_ai26_specific() -> None:
    """A floor-free policy must not reject the same pre-floor record.

    Guards the reverse error: an accidental global floor, or a floor that silently
    disappears from `RealtimePolicy.ai26()`.
    """
    pre_floor = _canonical_record(published_at="2026-08-31T23:59:59+00:00")
    assert RealtimePolicy.ai26().publication_date_floor is not None
    assert RealtimePolicy().publication_date_floor is None
    assert analysis_eligibility(pre_floor, RealtimePolicy()) == (True, "eligible")
