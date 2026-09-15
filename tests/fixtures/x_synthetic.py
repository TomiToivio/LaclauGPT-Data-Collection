"""Synthetic X/Twitter parser fixtures — no real platform data."""
from __future__ import annotations

MODERN_TWEET = {
    "__typename": "Tweet",
    "rest_id": "1500000000000000001",
    "core": {
        "user_results": {
            "result": {
                "rest_id": "u-1",
                "core": {"screen_name": "synth_user", "name": "Synth User"},
                "legacy": {"followers_count": 500, "description": "Synthetic bio"},
                "avatar": {"image_url": "https://cdn.example.invalid/pfp.jpg"},
            }
        }
    },
    "legacy": {
        "created_at": "Mon Sep 09 12:00:00 +0000 2026",
        "full_text": "Synthetic post about AI policy #aipolicy",
        "lang": "en",
        "favorite_count": 12,
        "retweet_count": 2,
        "reply_count": 3,
        "quote_count": 1,
        "conversation_id_str": "1500000000000000001",
        "entities": {
            "hashtags": [{"text": "aipolicy"}],
            "user_mentions": [{"screen_name": "synth_other"}],
            "urls": [{"expanded_url": "https://example.invalid/report"}],
        },
        "extended_entities": {
            "media": [
                {
                    "media_url_https": "https://cdn.example.invalid/img.jpg",
                    "video_info": {
                        "variants": [
                            {"content_type": "video/mp4", "bitrate": 832000,
                             "url": "https://cdn.example.invalid/vid.mp4"},
                            {"content_type": "video/mp4", "bitrate": 282000,
                             "url": "https://cdn.example.invalid/vid-small.mp4"},
                        ]
                    },
                }
            ]
        },
    },
}

TIMELINE = {
    "data": {
        "user": {
            "result": {
                "timeline_v2": {
                    "timeline": {
                        "instructions": [
                            {
                                "type": "TimelineAddEntries",
                                "entries": [
                                    {
                                        "entryId": "tweet-1",
                                        "content": {
                                            "entryType": "TimelineTimelineItem",
                                            "itemContent": {
                                                "itemType": "TimelineTweet",
                                                "tweet_results": {"result": MODERN_TWEET},
                                            },
                                        },
                                    }
                                ],
                            }
                        ]
                    }
                }
            }
        }
    }
}

ADAPTIVE = {
    "globalObjects": {
        "tweets": {
            "1500000000000000001": {
                "id_str": "1500000000000000001",
                "full_text": "Synthetic adaptive payload post",
                "created_at": "Mon Sep 09 12:00:00 +0000 2026",
                "user_id_str": "u-1",
                "entities": {},
            }
        },
        "users": {"u-1": {"id_str": "u-1", "screen_name": "synth_user", "name": "Synth User"}},
    }
}