"""Backwards-compatible import/export adapters for AC/DT-era datasets.

The adapters are intentionally loss-preserving. They normalize fields required by the
current canonical record while retaining the complete legacy row under ``record.legacy``.
They never infer ideology, discourse, frames, actors' motives, or missing provenance.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from .models import (
    CanonicalRecord,
    CollectionProvenance,
    ContentSection,
    MediaReference,
    RawCaptureSection,
    SourceSection,
)

COMPAT_VERSION = "acdt-collection-compat/1.0"


def _str(value: Any) -> str:
    return "" if value is None else str(value)


def _list(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, (list, tuple, set)):
        return [_str(item) for item in value if _str(item)]
    return [_str(value)]


def _media(value: Any) -> list[MediaReference]:
    if not value:
        return []
    values = value if isinstance(value, (list, tuple)) else [value]
    result: list[MediaReference] = []
    for index, item in enumerate(values):
        if isinstance(item, Mapping):
            known = {
                "kind",
                "url",
                "media_index",
                "local_ref",
                "object_ref",
                "checksum",
                "metadata",
            }
            metadata = deepcopy(dict(item.get("metadata") or {}))
            metadata.update({key: deepcopy(val) for key, val in item.items() if key not in known})
            result.append(
                MediaReference(
                    kind=_str(item.get("kind") or item.get("type")) or "media",
                    url=_str(item.get("url")),
                    media_index=int(item.get("media_index", index) or index),
                    local_ref=_str(item.get("local_ref")),
                    object_ref=_str(item.get("object_ref")),
                    checksum=_str(item.get("checksum")),
                    metadata=metadata,
                )
            )
        else:
            result.append(MediaReference(kind="media", url=_str(item), media_index=index))
    return result


def import_legacy_twitter(row: Mapping[str, Any], *, study_id: str | None = None) -> CanonicalRecord:
    """Normalize an old Twitter/X-style row without discarding source fields."""
    original = deepcopy(dict(row))
    document_id = _str(row.get("document_id") or row.get("tweet_id") or row.get("id"))
    source_url = _str(row.get("source_url") or row.get("url") or row.get("tweet_url"))
    if not source_url:
        if not document_id:
            raise ValueError("legacy Twitter row requires source_url/url or a stable tweet/document id")
        source_url = f"x:{document_id}"

    actor_id = _str(row.get("actor_id") or row.get("author_id") or row.get("user_id"))
    author = _str(row.get("author") or row.get("username") or row.get("screen_name"))
    created_at = _str(row.get("created_at") or row.get("timestamp") or row.get("date")) or None
    language = _str(row.get("language") or row.get("lang"))
    text = _str(row.get("text") or row.get("full_text") or row.get("content"))

    hashtags = _list(row.get("hashtags"))
    mentions = _list(row.get("mentions") or row.get("user_mentions"))
    links = _list(row.get("links") or row.get("urls"))
    interaction_ids = {
        key: _str(value)
        for key, value in {
            "parent_document_id": row.get("parent_document_id") or row.get("reply_to_id") or row.get("in_reply_to_status_id"),
            "repost_of": row.get("repost_of") or row.get("retweet_of") or row.get("retweeted_status_id"),
            "quote_of": row.get("quote_of") or row.get("quoted_status_id"),
            "conversation_id": row.get("conversation_id"),
            "reply_to_actor": row.get("reply_to_actor") or row.get("in_reply_to_screen_name"),
            "repost_actor": row.get("repost_actor") or row.get("retweeted_screen_name"),
            "quote_actor": row.get("quote_actor") or row.get("quoted_screen_name"),
        }.items()
        if _str(value)
    }

    native_ids = {"document_id": document_id} if document_id else {}
    if actor_id:
        native_ids["actor_id"] = actor_id

    media_references = _media(row.get("media_references") or row.get("media"))
    translation_metadata = deepcopy(dict(row.get("translation_metadata") or {}))

    record = CanonicalRecord(
        source_url=source_url,
        source_native_ids=native_ids,
        raw_capture=RawCaptureSection(
            payload=original,
            content_type="application/x-legacy-acdt-row",
            metadata={"preservation": "legacy-row-snapshot", "compatibility_version": COMPAT_VERSION},
        ),
        source=SourceSection(
            platform=_str(row.get("platform")) or "twitter",
            source_type=_str(row.get("source_type")) or "social_post",
            author=author,
            author_fullname=_str(row.get("author_fullname") or row.get("name")),
            created_at=created_at,
            collection_method="legacy_acdt_import",
            language=language,
            raw_metadata={
                "hashtags": hashtags,
                "mentions": mentions,
                "links": links,
                "interaction_ids": interaction_ids,
                "engagement": deepcopy(dict(row.get("engagement") or {})),
                "collection_query": row.get("collection_query") or row.get("query"),
                "collection_keywords": _list(row.get("collection_keywords") or row.get("keywords")),
                "collection_hashtags": _list(row.get("collection_hashtags")),
                "platform_metadata": deepcopy(dict(row.get("platform_metadata") or {})),
                "translation_metadata": translation_metadata,
            },
        ),
        content=ContentSection(
            text=text,
            language=language or None,
            translated_text=row.get("translated_text"),
            media_references=media_references,
            file_references=_list(row.get("file_references")),
        ),
        provenance=[
            CollectionProvenance(
                module="acdt_compat.import_legacy_twitter",
                module_version=COMPAT_VERSION,
                transformations=["legacy_row_to_canonical_record"],
                metadata={
                    "study_id": study_id,
                    "legacy_format": "twitter_x_row",
                    "missing_fields_not_inferred": True,
                    "translation_metadata": translation_metadata or None,
                },
            )
        ],
        legacy={
            "compatibility_version": COMPAT_VERSION,
            "format": "twitter_x_row",
            "original": original,
        },
    )
    record.refresh_human_readable()
    return record


def import_legacy_manifesto(row: Mapping[str, Any], *, study_id: str | None = None) -> CanonicalRecord:
    """Normalize a manifesto/document row while preserving scaling and coding fields."""
    original = deepcopy(dict(row))
    document_id = _str(row.get("document_id") or row.get("manifesto_id") or row.get("id"))
    source_url = _str(row.get("source_url") or row.get("url"))
    if not source_url:
        if not document_id:
            raise ValueError("legacy manifesto row requires source_url/url or a stable document id")
        source_url = f"manifesto:{document_id}"

    language = _str(row.get("language") or row.get("lang"))
    translation_metadata = deepcopy(dict(row.get("translation_metadata") or {}))
    record = CanonicalRecord(
        source_url=source_url,
        source_native_ids={"document_id": document_id} if document_id else {},
        raw_capture=RawCaptureSection(
            payload=original,
            content_type="application/x-legacy-manifesto-row",
            metadata={"preservation": "legacy-row-snapshot", "compatibility_version": COMPAT_VERSION},
        ),
        source=SourceSection(
            platform=_str(row.get("platform")) or "document",
            source_type=_str(row.get("source_type")) or "manifesto",
            author=_str(row.get("party") or row.get("author")),
            created_at=_str(row.get("date") or row.get("created_at")) or None,
            collection_method="legacy_acdt_import",
            language=language,
            raw_metadata={
                "country": row.get("country"),
                "election": row.get("election"),
                "manifesto_type": row.get("manifesto_type"),
                "translation_metadata": translation_metadata,
            },
        ),
        content=ContentSection(
            text=_str(row.get("text") or row.get("content")),
            title=row.get("title"),
            language=language or None,
            translated_text=row.get("translated_text"),
            media_references=_media(row.get("media_references") or row.get("media")),
            file_references=_list(row.get("file_references")),
        ),
        provenance=[
            CollectionProvenance(
                module="acdt_compat.import_legacy_manifesto",
                module_version=COMPAT_VERSION,
                transformations=["legacy_row_to_canonical_record"],
                metadata={
                    "study_id": study_id,
                    "legacy_format": "manifesto_row",
                    "missing_fields_not_inferred": True,
                    "translation_metadata": translation_metadata or None,
                },
            )
        ],
        legacy={
            "compatibility_version": COMPAT_VERSION,
            "format": "manifesto_row",
            "original": original,
        },
    )
    record.refresh_human_readable()
    return record


def export_legacy_row(record: CanonicalRecord) -> dict[str, Any]:
    """Round-trip a compatibility import and overlay canonical source-safe updates."""
    original = record.legacy.get("original")
    result: dict[str, Any] = deepcopy(original) if isinstance(original, dict) else {}
    result.update(
        {
            "source_url": record.source_url,
            "document_id": record.source_native_ids.get("document_id"),
            "actor_id": record.source_native_ids.get("actor_id"),
            "platform": record.source.platform,
            "source_type": record.source.source_type,
            "author": record.source.author,
            "author_fullname": record.source.author_fullname,
            "created_at": record.source.created_at,
            "language": record.source.language or record.content.language,
            "text": record.content.text,
            "translated_text": record.content.translated_text,
            "hashtags": deepcopy(record.source.raw_metadata.get("hashtags", [])),
            "mentions": deepcopy(record.source.raw_metadata.get("mentions", [])),
            "links": deepcopy(record.source.raw_metadata.get("links", [])),
            "interaction_ids": deepcopy(record.source.raw_metadata.get("interaction_ids", {})),
            "translation_metadata": deepcopy(record.source.raw_metadata.get("translation_metadata", {})),
            "media_references": [item.model_dump(mode="json") for item in record.content.media_references],
            "file_references": list(record.content.file_references),
            "compatibility_version": COMPAT_VERSION,
        }
    )
    return result
