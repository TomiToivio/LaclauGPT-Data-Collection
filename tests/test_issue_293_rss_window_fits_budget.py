"""The RSS window must fit its allocation (issue #293).

The stage used to size its window from the per-source limit alone — ``rss_limit // per_source_limit``
feeds at ``per_source_limit`` each — which produced a window the store budget could not consume and,
once the fetch was capped, cut the number of feeds polled per cycle. The budget has to size the
window, so ``feeds * depth <= rss_limit`` holds by construction and every rotation slot is polled.

The acceptance condition in the issue is exactly this invariant:
``max_feeds * per_feed_limit <= rss_allocation``.
"""

from __future__ import annotations

import pytest

from laclaugpt_data_collection.ai26_laskin_runner import _rss_window


def test_the_live_numbers_poll_every_window_feed():
    """8 feeds against a 20-record allocation: all 8 polled, 2 candidates each."""
    feeds, depth = _rss_window(8, 20)
    assert (feeds, depth) == (8, 2)
    assert feeds * depth <= 20


def test_the_old_sizing_polled_half_the_window():
    """Keeps the defect visible: 20 // 5 = 4 feeds, so four slots were never reached."""
    assert min(8, max(1, 20 // 5)) == 4


@pytest.mark.parametrize("max_feeds", [1, 2, 4, 8, 16, 32, 100])
@pytest.mark.parametrize("rss_limit", [1, 2, 4, 5, 19, 20, 40])
def test_the_window_always_fits_the_allocation(max_feeds: int, rss_limit: int):
    feeds, depth = _rss_window(max_feeds, rss_limit)
    assert feeds >= 0 and depth >= 0
    assert feeds * depth <= rss_limit, (max_feeds, rss_limit, feeds, depth)


def test_more_feeds_than_budget_polls_only_what_fits():
    """32 feeds against 20 records: 20 feeds at one candidate, not 32 at one."""
    assert _rss_window(32, 20) == (20, 1)


def test_no_allocation_polls_nothing():
    assert _rss_window(8, 0) == (0, 0)
    assert _rss_window(8, -5) == (0, 0)


def test_a_tiny_allocation_still_polls_one_feed_one_deep():
    assert _rss_window(8, 1) == (1, 1)
