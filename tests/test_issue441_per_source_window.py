"""#441: the per-source sampling window is a decision, so it is named and bounded.

Every platform poll returns the newest N items. At N=5 a 1–2 h interval on a busy account (7–16 posts)
lost most of it, and a real timeline does not hand back exactly five items on every request — that was
the cap, not the feed.
"""
from __future__ import annotations

import pytest

from laclaugpt_data_collection.ai26_laskin_runner import per_source_limit_default


def test_the_default_window_covers_a_burst_and_stays_inside_the_daily_cap():
    # 75–100 records/day per source, four polls a day: 25 per poll is the smallest window that can
    # reach the cap instead of making it decorative.
    assert per_source_limit_default({}) == 25


def test_a_study_can_widen_the_window_without_a_code_change():
    assert per_source_limit_default({"LACLAUGPT_AI26_PER_SOURCE_LIMIT": "40"}) == 40


@pytest.mark.parametrize("raw", ["", "  ", "nonsense", "0", "-3"])
def test_an_unusable_value_falls_back_rather_than_polling_for_nothing(raw):
    assert per_source_limit_default({"LACLAUGPT_AI26_PER_SOURCE_LIMIT": raw}) == 25


def test_the_window_is_bounded_so_one_poll_cannot_become_a_full_timeline_download():
    assert per_source_limit_default({"LACLAUGPT_AI26_PER_SOURCE_LIMIT": "100000"}) == 200
