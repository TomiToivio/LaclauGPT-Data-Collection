"""#441 follow-up: the RSS depth is a budget fact, not the platform polling window.

#444 raised the per-poll platform window from 5 to 25 (env-configurable). That
window was still passed into `_rss_window`, which sizes the RSS fetch as
``feeds * depth <= rss_limit`` (#293). With the defaults the measured effect was:

    per_source_limit=25, rss_limit=20
    before: (4 feeds, depth 5)   after: (1 feed, depth 20)

One feed per tick means the 36-feed manifest rotates in 36 cycles instead of 9,
and a feed publishing three items between its turns loses the middle one forever
— the exact loss #293 fixed by shrinking the feed count rather than the depth.

These tests pin the separation so a future window change cannot re-create it.
"""

from __future__ import annotations

import inspect

from laclaugpt_data_collection.ai26_laskin_runner import (
    _rss_window,
    per_source_limit_default,
)


def test_rss_window_is_the_declared_depth_regardless_of_the_platform_window():
    declared = per_source_limit_default({})
    rss_limit = 40 - min(40 // 2, 6 * declared)
    assert _rss_window(8, rss_limit) == (4, 5)


def test_rss_window_does_not_accept_the_platform_window():
    params = list(inspect.signature(_rss_window).parameters)
    assert params == ["max_feeds", "rss_limit", "declared_depth"], (
        "passing per_source_limit into _rss_window couples the RSS budget to the "
        "platform polling window and starves the feed rotation (#293, #441)"
    )


def test_the_platform_window_is_still_the_widened_one():
    """The fix above must not quietly revert #444's burst window."""
    assert per_source_limit_default({}) >= 10
