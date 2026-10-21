"""The RSS window must fit its allocation (issue #293).

The stage used to size its window from the per-source limit alone — ``rss_limit // per_source_limit``
feeds at ``per_source_limit`` each — which produced a window the store budget could not consume and,
once the fetch was capped, cut the number of feeds polled per cycle. The budget sizes the window, so
``feeds * depth <= rss_limit`` holds by construction and every rotation slot is polled.

The acceptance condition in the issue is exactly this invariant:
``max_feeds * per_feed_limit <= rss_allocation``.

Two ways of satisfying it exist. This one keeps the declared depth and shrinks the feed count: 4
feeds at 5 candidates. Shrinking the *depth* instead (8 feeds at 2) also fits the allocation, but it
changes which records a cycle can store — only a feed's two newest items are fetched, so the third
newest is never collected once two newer ones exist — and the stored set stops being the prefix of
an unbounded fetch that #301 pinned. The depth therefore stays the declared
``per_source_limit``; the loss of per-feed cadence is recovered by the rotation, not by depth.
"""

from __future__ import annotations

import pytest

from laclaugpt_data_collection.ai26_laskin_runner import _rss_window


def test_the_live_numbers_poll_every_window_feed():
    """8 feed slots against a 20-record allocation: 4 feeds at the declared depth of 5."""
    feeds, depth = _rss_window(8, 20, 5)
    assert (feeds, depth) == (4, 5)
    assert feeds * depth <= 20
    assert depth == 5, "the declared per-source depth is what makes the stored set unchanged"


def test_reducing_depth_would_still_fit_but_is_not_used():
    """Keeps the alternative visible: 8 x 2 also fits 20, at the cost of item skipping."""
    assert 8 * 2 <= 20
    feeds, depth = _rss_window(8, 20, 5)
    assert (feeds, depth) != (8, 2)


def test_the_old_sizing_polled_half_the_window():
    """Keeps the defect visible: 20 // 5 = 4 feeds, so four slots were never reached."""
    assert min(8, max(1, 20 // 5)) == 4


@pytest.mark.parametrize("max_feeds", [1, 2, 4, 8, 16, 32, 100])
@pytest.mark.parametrize("rss_limit", [1, 2, 4, 5, 19, 20, 40])
def test_the_window_always_fits_the_allocation(max_feeds: int, rss_limit: int):
    feeds, depth = _rss_window(max_feeds, rss_limit)
    assert feeds >= 0 and depth >= 0
    assert feeds * depth <= rss_limit, (max_feeds, rss_limit, feeds, depth)


@pytest.mark.parametrize("per_source_limit", [1, 2, 3, 5, 8, 10])
def test_a_declared_depth_is_never_exceeded(per_source_limit: int):
    _feeds, depth = _rss_window(8, 40, per_source_limit)
    assert depth <= per_source_limit


def test_more_feeds_than_budget_polls_only_what_fits():
    """32 feed slots against 20 records: 4 feeds at 5, not 32 at one."""
    assert _rss_window(32, 20, 5) == (4, 5)


def test_no_allocation_polls_nothing():
    assert _rss_window(8, 0) == (0, 0)
    assert _rss_window(8, -5) == (0, 0)


def test_a_tiny_allocation_still_polls_one_feed_one_deep():
    assert _rss_window(8, 1) == (1, 1)
