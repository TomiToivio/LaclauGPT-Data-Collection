"""Regression tests for issue #412: records pinned in waiting_media with no media reference.

The failure was not that a download failed — it is that a record said it was waiting for media it
did not reference, so no job could ever be produced, and the cycle summary counted it as a generic
``skipped``. 59 AI26 records (56 arXiv, 3 mastodon) sat in that state for three weeks.
"""
from __future__ import annotations

from types import SimpleNamespace

from laclaugpt_data_collection.distributed_media_runner import _has_media_reference
from laclaugpt_data_collection.handoff import build_handoff
from laclaugpt_data_collection.storage.remote import MongoRecordStore


def pinned_document(*, url: str = "https://arxiv.org/abs/2610.20606v1", media=None) -> dict:
    """The live shape: _id, handoff, raw_capture, source, source_url — and no media field at all."""
    document = {
        "_id": "record-1",
        "project_id": "ai26",
        "collection_id": "ai26",
        "source_url": url,
        "source": {
            "platform": "arxiv",
            "source_type": "article",
            "created_at": "2026-10-22T10:00:00Z",
        },
        "raw_capture": {"content_type": "application/vnd.arxiv.metadata+json"},
        "handoff": {"status": "waiting_media", "reason": "waiting_media", "handoff_key": "key-1",
                    "run_id": "ai26-distributed-001"},
    }
    if media is not None:
        document["content"] = {"text": "AI research", "media_references": media}
    return document


class FakeCollection:
    def __init__(self, documents):
        self.documents = documents
        self.updates = []
        self.last_query = None

    def find(self, query):
        self.last_query = query
        return FakeCursor(self.documents)

    def update_one(self, query, update):
        self.updates.append((query, update))
        doc = next((d for d in self.documents if d["_id"] == query["_id"]), None)
        if doc is None or doc["handoff"]["status"] != query["handoff.status"] or (
            doc["handoff"].get("handoff_key") != query["handoff.handoff_key"]
        ):
            return SimpleNamespace(modified_count=0)
        doc["handoff"] = update["$set"]["handoff"]
        return SimpleNamespace(modified_count=1)


class FakeCursor:
    def __init__(self, documents):
        self.documents = documents

    def limit(self, limit):
        return self.documents[:limit]


def store_for(documents):
    store = MongoRecordStore.__new__(MongoRecordStore)
    store.project_id = "ai26"
    store._collection = FakeCollection(documents)
    return store


def test_a_record_with_no_media_reference_is_promoted_to_ready():
    """The #412 case: nothing to download, so nothing to wait for."""
    doc = pinned_document()
    store = store_for([doc])

    assert store.reconcile_waiting_media(collection_id="ai26") == 1
    assert doc["handoff"]["status"] == "ready"
    # ``build_handoff`` keeps ``source_ready`` for a record whose media requirement is "none":
    # only a *resolved* media set rewrites the reason to media_ready. The status is the contract.
    assert doc["handoff"]["reason"] == "source_ready"
    # The reconstruction keeps the producer's run id.
    assert doc["handoff"]["run_id"] == "ai26-distributed-001"


def test_the_repair_no_longer_filters_for_resolved_media():
    """The old $elemMatch on object_ref is what hid this class; it must not come back."""
    doc = pinned_document()
    store = store_for([doc])
    store.reconcile_waiting_media(collection_id="ai26")

    query = store._collection.last_query
    assert query["handoff.status"] == "waiting_media"
    assert "content.media_references" not in query


def test_a_record_with_an_unresolved_reference_stays_waiting():
    """A genuine wait is still a wait: recomputing must not promote it."""
    doc = pinned_document(media=[{"url": "https://example.org/paper.pdf", "media_index": 0}])
    store = store_for([doc])
    before = dict(doc["handoff"])

    assert store.reconcile_waiting_media(collection_id="ai26") == 0
    assert doc["handoff"] == before
    assert store._collection.updates == []


def test_one_call_repairs_both_stale_classes():
    """#287 (media resolved, envelope stale) and #412 (no media at all) together."""
    resolved = pinned_document(url="https://arxiv.org/abs/2610.11111v1",
                               media=[{"url": "https://example.org/a.pdf", "media_index": 0,
                                       "object_ref": "s3://bucket/a.pdf", "checksum": "abc"}])
    resolved["_id"] = "record-2"
    resolved["handoff"] = {**build_handoff(
        {k: v for k, v in resolved.items() if k != "handoff"}, project_id="ai26"),
        "status": "waiting_media", "handoff_key": "key-2", "run_id": "ai26-distributed-001"}

    reference_less = pinned_document()
    store = store_for([reference_less, resolved])

    assert store.reconcile_waiting_media(collection_id="ai26") == 2
    assert reference_less["handoff"]["status"] == "ready"
    assert reference_less["handoff"]["reason"] == "source_ready"
    assert resolved["handoff"]["status"] == "ready"
    assert resolved["handoff"]["reason"] == "media_ready"


def test_has_media_reference_matches_what_the_downloader_can_use():
    assert _has_media_reference({"source_url": "x"}) is False
    assert _has_media_reference({"content": {}}) is False
    assert _has_media_reference({"content": {"media_references": []}}) is False
    # a reference without a url is not a job
    assert _has_media_reference({"content": {"media_references": [{"media_index": 0}]}}) is False
    assert _has_media_reference({"content": {"media_references": [{"url": "https://e.org/a.pdf"}]}}) is True
    # the top-level form wins when both exist
    assert _has_media_reference({"media_references": [{"url": "https://e.org/a.pdf"}]}) is True


# --------------------------------------------------------------------------- #
# The actual cause: the media runner applied Brazil26's allowlist to every study.
# --------------------------------------------------------------------------- #

def test_the_ai26_media_cycle_is_not_bound_by_brazils_allowlist(tmp_path):
    """#412 regression: ai26 must not inherit X/Instagram/TikTok-only media policy."""
    from laclaugpt_data_collection.distributed_media_runner import _allowed_platforms

    config = tmp_path / "config"
    config.mkdir()
    (config / "ai26.sources.toml").write_text(
        '[[feeds]]\nname = "arxiv"\nurl = "https://example.org/feed"\n', encoding="utf-8")
    (config / "brazil26.sources.toml").write_text(
        'enabled_platforms = ["x", "instagram", "tiktok"]\n', encoding="utf-8")

    study_config = tmp_path / "ai26.yaml"
    study_config.write_text("study: ai26\n", encoding="utf-8")

    assert _allowed_platforms(study_config, tmp_path) is None, (
        "an AI26 manifest declares no media policy; the study must stay unconstrained"
    )


def test_brazil26_keeps_its_allowlist(tmp_path):
    from laclaugpt_data_collection.distributed_media_runner import _allowed_platforms

    config = tmp_path / "config"
    config.mkdir()
    (config / "brazil26.sources.toml").write_text(
        'enabled_platforms = ["x", "instagram", "tiktok"]\n', encoding="utf-8")
    study_config = tmp_path / "brazil26.yaml"
    study_config.write_text("study: brazil26\n", encoding="utf-8")

    assert _allowed_platforms(study_config, tmp_path) == frozenset({"x", "instagram", "tiktok"})


def test_a_study_manifest_that_declares_platforms_is_honoured(tmp_path):
    from laclaugpt_data_collection.distributed_media_runner import _allowed_platforms

    config = tmp_path / "config"
    config.mkdir()
    (config / "other26.sources.toml").write_text(
        'enabled_platforms = ["rss", "bluesky"]\n', encoding="utf-8")
    study_config = tmp_path / "other26.yaml"
    study_config.write_text("study: other26\n", encoding="utf-8")

    assert _allowed_platforms(study_config, tmp_path) == frozenset({"rss", "bluesky"})


def test_no_manifest_leaves_the_study_unconstrained(tmp_path):
    from laclaugpt_data_collection.distributed_media_runner import _allowed_platforms

    study_config = tmp_path / "ai26.yaml"
    study_config.write_text("study: ai26\n", encoding="utf-8")
    assert _allowed_platforms(study_config, tmp_path) is None
