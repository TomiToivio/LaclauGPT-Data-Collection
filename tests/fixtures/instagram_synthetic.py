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

PHASE1_REEL_WITH_REFERENCE = {
    "pk": "3300000000000000132",
    "id": "3300000000000000132",
    "code": "SynthReel132",
    "__typename": "XDTGraphVideo",
    "media_type": 2,
    "caption": {"text": "Synthetic Phase 1 reel fixture"},
    "taken_at": 1789898400,
    "user": {
        "username": "synthetic_phase1_ig",
        "full_name": "Synthetic Researcher",
        "pk": "ig-user-132",
        "is_verified": False,
    },
    "video_versions": [{"url": "https://cdn.example.invalid/phase1-132.mp4"}],
    "referenced_media": {
        "pk": "3300000000000000131",
        "code": "SynthSource131",
    },
}

PHASE1_REEL_RESPONSE = {
    "items": [PHASE1_REEL_WITH_REFERENCE],
    "paging_info": {"more_available": False},
}
