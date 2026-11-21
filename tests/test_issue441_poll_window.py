"""#441: a platform poll must be wide enough to see a burst.

The collector shipped `per_source_limit=5`, and every high-volume platform row returned
exactly 5 records in 100 % of its polls. A real timeline does not hand back exactly five
items on every request — that was the cap — and it clipped the intervals that matter: a
1–2 h gap holding 7–16 posts lost everything above the window (40 % of Timnit Gebru's
posts, 17 % of EFF's over the measured period).

These tests pin the two halves of the fix and the boundary between them: the platform
window is burst-sized, and the RSS depth stays budget-shaped (#293) so raising the
platform window cannot collapse feed coverage to a single feed per tick.
"""

from __future__ import annotations

import inspect

from laclaugpt_data_collection.ai26_laskin_runner import (
    _rss_window,
    build_arg_parser,
    run_phase1_laskin,
)

# The widest burst measured in #441 was 16 posts in a 2 h interval. Ten times that leaves
# room for a longer admission gap without approaching the tick's 40-record cap.
MINIMUM_BURST_WINDOW = 25


def test_platform_poll_window_covers_a_burst():
    default = inspect.signature(run_phase1_laskin).parameters["per_source_limit"].default
    assert default >= MINIMUM_BURST_WINDOW, (
        f"per_source_limit default is {default}; a poll narrower than {MINIMUM_BURST_WINDOW} "
        "clips the bursts #441 measured"
    )


def test_cli_default_matches_the_function_default():
    parser = build_arg_parser()
    cli_default = parser.get_default("per_source_limit")
    function_default = inspect.signature(run_phase1_laskin).parameters[
        "per_source_limit"
    ].default
    assert cli_default == function_default, (
        "the wrapper would collect with a different window than the library default"
    )


def test_raising_the_platform_window_does_not_starve_the_feed_rotation():
    """The RSS depth is a budget fact, not the platform polling cap (#293 vs #441)."""
    feeds, depth = _rss_window(8, 20)
    assert (feeds, depth) == (4, 5)
    # And explicitly: it does not read the platform window at all.
    assert list(inspect.signature(_rss_window).parameters) == [
        "max_feeds",
        "rss_limit",
        "declared_depth",
    ]
