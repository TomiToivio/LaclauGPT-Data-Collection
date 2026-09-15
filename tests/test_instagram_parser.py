"""Instagram parser tests on synthetic fixtures only."""
from __future__ import annotations

from laclaugpt_data_collection.collectors.platforms import instagram
from tests.fixtures import instagram_synthetic as fx

PAGE = "https://www.instagram.com/synth_ig/"


def test_capture_feed() -> None:
    items = instagram.capture(fx.FEED, PAGE, "api/v1/feed/user/synth_ig/")
    assert len(items) == 1
    assert items[0]["pk"] == "3300000000000000001"


def test_map_item_shape() -> None:
    mapped = instagram.map_item(fx.MEDIA_ITEM, {"source_platform_url": PAGE})
    assert mapped["id"] == "SynthCode1"
    assert mapped["author"] == "synth_ig"
    assert mapped["media_type"] == "photo"
    assert mapped["hashtags"] == "aipolicy"
    assert mapped["timestamp"] == "2024-09-10T20:26:40Z"
    assert mapped["url"] == "https://www.instagram.com/p/SynthCode1"
    assert mapped["num_likes"] == 44


def test_carousel_children_are_media_assets() -> None:
    items = instagram.capture({"items": [fx.CAROUSEL_ITEM]}, PAGE, "api/v1/feed/")
    assert len(items) == 1
    mapped = instagram.map_item(items[0])
    assert mapped["media_type"] == "carousel"
    assert "https://cdn.example.invalid/c1.jpg" in mapped["image_urls"]
    assert "https://cdn.example.invalid/c2.jpg" in mapped["image_urls"]


def test_capture_ignores_other_platforms() -> None:
    assert instagram.capture(fx.FEED, "https://tiktok.com/@x", "api/v1/feed/") == []


def test_logging_endpoints_ignored() -> None:
    assert instagram.capture(fx.FEED, PAGE, "api/v1/logging_client_events/") == []
