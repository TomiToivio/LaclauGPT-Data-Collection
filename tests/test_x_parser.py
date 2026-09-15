"""X/Twitter parser tests on synthetic fixtures only."""
from __future__ import annotations

from laclaugpt_data_collection.collectors.platforms import twitter
from tests.fixtures import x_synthetic as fx

PAGE = "https://x.com/synth_user"


def test_capture_timeline() -> None:
    tweets = twitter.capture(fx.TIMELINE, PAGE, "i/api/graphql/abc/UserTweets?variables=%7B%7D")
    assert len(tweets) == 1
    assert tweets[0]["rest_id"] == "1500000000000000001"


def test_capture_adaptive() -> None:
    tweets = twitter.capture(fx.ADAPTIVE, PAGE, "i/api/2/timeline/profile/adaptive.json")
    assert len(tweets) == 1
    assert tweets[0]["id"] == "1500000000000000001"
    assert tweets[0]["user"]["screen_name"] == "synth_user"


def test_capture_ignores_non_post_endpoints() -> None:
    assert twitter.capture(fx.TIMELINE, PAGE, "i/api/graphql/abc/HomeLatestPhotos") == []


def test_capture_ignores_other_platforms() -> None:
    assert twitter.capture(fx.TIMELINE, "https://instagram.com/x", "UserTweets") == []


def test_map_item_shape() -> None:
    mapped = twitter.map_item(fx.MODERN_TWEET, {"source_platform_url": PAGE})
    assert mapped["id"] == "1500000000000000001"
    assert mapped["author"] == "synth_user"
    assert mapped["timestamp"] == "2026-09-09T12:00:00Z"
    assert mapped["hashtags"] == "aipolicy"
    assert mapped["mentions"] == "synth_other"
    assert mapped["images"] == "https://cdn.example.invalid/img.jpg"
    # best-bitrate mp4 variant wins
    assert mapped["videos"] == "https://cdn.example.invalid/vid.mp4"
    assert mapped["like_count"] == 12
    assert mapped["is_reply"] == "no"
    assert mapped["link"] == "https://x.com/synth_user/status/1500000000000000001"


def test_ids_are_strings() -> None:
    mapped = twitter.map_item(fx.MODERN_TWEET)
    assert isinstance(mapped["id"], str)