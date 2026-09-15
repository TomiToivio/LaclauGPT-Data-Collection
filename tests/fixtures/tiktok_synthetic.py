"""Synthetic TikTok parser fixtures — no real platform data."""
from __future__ import annotations

import json

POST = {
    "id": "7300000000000000001",
    "desc": "Synthetic AI governance discussion #airegulation",
    "createTime": 1726000000,
    "author": {
        "id": "author-1",
        "uniqueId": "synthetic_researcher",
        "nickname": "Synthetic Researcher",
        "avatarThumb": "https://cdn.example.invalid/avatar.jpg",
    },
    "authorStats": {"followerCount": 1200, "heartCount": 3400, "videoCount": 42},
    "stats": {"diggCount": 100, "commentCount": 11, "shareCount": 5, "playCount": 900},
    "video": {
        "downloadAddr": "https://cdn.example.invalid/video.mp4",
        "cover": "https://cdn.example.invalid/cover.jpg",
        "duration": 30,
    },
    "music": {"id": "m1", "title": "Synthetic Sound", "authorName": "Synth Author"},
    "textExtra": [{"hashtagName": "airegulation"}, {"hashtagName": "ai"}],
    "challenges": [{"title": "airegulation"}],
    "diversificationLabels": ["technology"],
    "warnInfo": [],
}

COMMENT = {
    "cid": "c-0001",
    "aweme_id": "7300000000000000001",
    "text": "Synthetic comment text about AI policy",
    "create_time": 1726000100,
    "digg_count": 3,
    "reply_comment_total": 1,
    "user": {"uid": "u-1", "unique_id": "synthetic_commenter", "nickname": "Synthetic Commenter"},
    "share_info": {"url": "https://www.tiktok.com/@x/video/7300000000000000001"},
}

USER_DETAIL = {
    "userInfo": {
        "user": {
            "id": "author-1",
            "uniqueId": "synthetic_researcher",
            "nickname": "Synthetic Researcher",
            "signature": "Synthetic bio",
            "avatarLarger": "https://cdn.example.invalid/avatar.jpg",
        },
        "stats": {"followerCount": 1200, "followingCount": 100, "heartCount": 3400, "videoCount": 42},
    }
}

CHALLENGE_DETAIL = {
    "challengeInfo": {
        "challenge": {"id": "tag-1", "title": "airegulation"},
        "statsV2": {"viewCount": 500000, "videoCount": 210},
    }
}

SIGI_HTML = (
    '<html><head><script id="SIGI_STATE" type="application/json">'
    + json.dumps({"ItemModule": {POST["id"]: POST}})
    + "</script></head><body></body></html>"
)

UNIVERSAL_DATA = {
    "__DEFAULT_SCOPE__": {
        "webapp.video-detail": {"itemInfo": {"itemStruct": POST}},
    }
}


def item_list_payload() -> dict:
    return {"itemList": [POST]}