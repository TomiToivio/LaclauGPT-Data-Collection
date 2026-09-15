"""TikTok parser tests on synthetic fixtures only."""
from __future__ import annotations

import json

from laclaugpt_data_collection.collectors.platforms import tiktok, tiktok_extras
from tests.fixtures import tiktok_synthetic as fx

PAGE = "https://www.tiktok.com/@synthetic_researcher"


def test_capture_item_list() -> None:
    posts = tiktok.capture(fx.item_list_payload(), PAGE, "api/post/item_list/?count=10")
    assert len(posts) == 1
    assert posts[0]["id"] == "7300000000000000001"


def test_capture_sigi_html() -> None:
    posts = tiktok.capture(fx.SIGI_HTML, PAGE, "https://www.tiktok.com/@synthetic_researcher")
    assert len(posts) == 1


def test_capture_universal_data() -> None:
    posts = tiktok.capture(fx.UNIVERSAL_DATA, PAGE, "")
    assert len(posts) == 1


def test_capture_ignores_other_platforms() -> None:
    assert tiktok.capture(fx.item_list_payload(), "https://instagram.com/x", "api/post/item_list") == []


def test_capture_ignores_preload() -> None:
    assert tiktok.capture(fx.item_list_payload(), PAGE, "api/preload/item_list/?count=10") == []


def test_map_item_shape() -> None:
    mapped = tiktok.map_item(fx.POST, {"source_platform_url": PAGE})
    assert mapped["id"] == "7300000000000000001"
    assert mapped["author"] == "synthetic_researcher"
    assert mapped["author_full"] == "Synthetic Researcher"
    assert mapped["timestamp"] == "2024-09-10T20:26:40Z"
    assert mapped["unix_timestamp"] == 1726000000
    assert mapped["hashtags"] == "airegulation,ai"
    assert mapped["video_url"].startswith("https://cdn.example.invalid/")
    assert mapped["likes"] == 100
    assert mapped["is_duet"] == "no"


def test_dedup_preserves_order() -> None:
    payload = {"itemList": [fx.POST, dict(fx.POST)]}
    posts = tiktok.capture(payload, PAGE, "api/post/item_list")
    assert len(posts) == 1


def test_comment_capture_and_record() -> None:
    raw = tiktok_extras.capture(
        {"comments": [fx.COMMENT]}, PAGE, "api/comment/list/?aweme_id=7300000000000000001")
    assert len(raw) == 1
    mapped = tiktok_extras.map_item(raw[0])
    assert mapped["record_kind"] == "comment"
    record = tiktok_extras.to_record(mapped)
    assert record is not None
    assert record.document_id == "c-0001"
    assert record.platform == "tiktok_comment"
    assert record.parent_document_id == "7300000000000000001"
    assert record.engagement["likes"] == 3
    assert record.text == "Synthetic comment text about AI policy"


def test_user_detail_capture_and_record() -> None:
    raw = tiktok_extras.capture(fx.USER_DETAIL, PAGE, "api/user/detail/?unique_id=synthetic_researcher")
    assert len(raw) == 1
    mapped = tiktok_extras.map_item(raw[0])
    record = tiktok_extras.to_record(mapped)
    assert record is not None
    assert record.document_id == "author-1"
    assert record.platform == "tiktok_user"
    assert record.engagement["followers"] == 1200


def test_challenge_detail_capture_and_record() -> None:
    raw = tiktok_extras.capture(fx.CHALLENGE_DETAIL, PAGE, "api/challenge/detail/?challengeName=airegulation")
    assert len(raw) == 1
    mapped = tiktok_extras.map_item(raw[0])
    record = tiktok_extras.to_record(mapped)
    assert record is not None
    assert record.document_id == "tag-1"
    assert record.platform == "tiktok_challenge"
    assert record.engagement["views"] == 500000


def test_aux_capture_ignores_unknown_urls() -> None:
    assert tiktok_extras.capture({"comments": [fx.COMMENT]}, PAGE, "api/post/item_list") == []
    assert tiktok_extras.capture("not json", PAGE, "api/comment/list/") == []


def test_json_body_string_accepted() -> None:
    posts = tiktok.capture(json.dumps(fx.item_list_payload()), PAGE, "api/post/item_list")
    assert len(posts) == 1
