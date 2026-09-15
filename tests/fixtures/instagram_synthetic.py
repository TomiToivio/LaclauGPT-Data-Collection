"""Synthetic Instagram parser fixtures — no real platform data."""
from __future__ import annotations

MEDIA_ITEM = {
    "pk": "3300000000000000001",
    "id": "3300000000000000001",
    "code": "SynthCode1",
    "__typename": "XDTGraphImage",
    "media_type": 1,
    "caption": {"text": "Synthetic caption about AI policy #aipolicy"},
    "taken_at": 1726000000,
    "user": {"username": "synth_ig", "full_name": "Synth IG", "pk": "u-9", "is_verified": False},
    "like_count": 44,
    "comment_count": 6,
    "image_versions2": {"candidates": [{"url": "https://cdn.example.invalid/ig.jpg"}]},
}

FEED = {"xdt_api__v1__feed": {"user_timeline_feed_connection": {"edges": [{"node": MEDIA_ITEM}]}}}

CAROUSEL_ITEM = {
    **MEDIA_ITEM,
    "pk": "3300000000000000002",
    "id": "3300000000000000002",
    "code": "SynthCode2",
    "media_type": 8,
    "carousel_media": [
        {"pk": "c1", "image_versions2": {"candidates": [{"url": "https://cdn.example.invalid/c1.jpg"}]}},
        {"pk": "c2", "image_versions2": {"candidates": [{"url": "https://cdn.example.invalid/c2.jpg"}]}},
    ],
}