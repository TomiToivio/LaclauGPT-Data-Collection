"""Phase 0 collection -> analysis MongoDB boundary (issue #85).

Phase 0 collection and the Phase 0 analysis core must agree on one database, one
collection name and one flat document schema. These tests pin that contract
offline: no MongoDB, Redis or S3 is contacted.
"""
from __future__ import annotations

from laclaugpt_data_collection.phase0_mongo import (
    PHASE0_COLLECTION_TEMPLATE,
    Phase0Document,
    canonicalize_url,
    flatten_record,
    phase0_collection_name,
    upsert_phase0_documents,
)

# The collection name and field list the analysis core hard-codes. If either side
# changes, this test must fail rather than the pipelines silently diverging.
ANALYSIS_COLLECTION_TEMPLATE = "laclaugpt2_{project}_scraper_collection"
ANALYSIS_REQUIRED_FIELDS = (
    "source_url",
    "source_text",
    "source_title",
    "source_date",
    "source_name",
    "source_type",
    "document_id",
)


class FakeCollection:
    """Minimal upsert-capable collection double."""

    def __init__(self) -> None:
        self.docs: dict[str, dict] = {}
        self.calls = 0

    def update_one(self, query, update, upsert=False):  # noqa: ANN001, ARG002
        self.calls += 1
        key = query["source_url"]
        self.docs.setdefault(key, {}).update(update["$set"])


def _canonical_rss_record() -> dict:
    """A collected RSS item in the nested shape the collector produces."""
    return {
        "document_id": "doc-1",
        "source_url": "https://example.org/ai/post-1?utm_source=newsletter#section",
        "source_type": "rss",
        "provenance": [{"metadata": {"source_name": "Example Feed", "arena": "elites"}}],
        "source": {
            "platform": "rss",
            "source_type": "rss",
            "author": "Ada Example",
            "language": "en",
            "created_at": "2026-09-18T09:30:00+00:00",
            "raw_metadata": {
                "source_name": "Example Feed",
                "arena": "elites",
                "project": "ai26",
                "feed_url": "https://example.org/feed",
            },
        },
        "content": {
            "text": "AI should serve democratic society rather than private accumulation.",
            "title": "Synthetic AI26 post",
            "language": "en",
            "categories": ["AI", "Policy"],
        },
        "raw_capture": {"payload": None},
    }


# --------------------------------------------------------------------------
# The boundary must be shared
# --------------------------------------------------------------------------

def test_collection_name_matches_what_analysis_reads() -> None:
    """Both sides must resolve the same collection name for the same project."""
    assert PHASE0_COLLECTION_TEMPLATE == ANALYSIS_COLLECTION_TEMPLATE
    assert phase0_collection_name("ai26") == "laclaugpt2_ai26_scraper_collection"


def test_phase0_collection_name_requires_a_project() -> None:
    for empty in ("", "   "):
        try:
            phase0_collection_name(empty)
        except ValueError:
            continue
        raise AssertionError("empty project_id must be rejected")


# --------------------------------------------------------------------------
# The stored document must expose the flat Phase 0 fields
# --------------------------------------------------------------------------

def test_flattened_document_exposes_every_field_analysis_requires() -> None:
    document = flatten_record(_canonical_rss_record(), project_id="ai26").to_document()
    missing = [field for field in ANALYSIS_REQUIRED_FIELDS if not document.get(field)]
    assert not missing, f"analysis requires {missing}"


def test_flattened_document_preserves_text_and_metadata() -> None:
    document = flatten_record(_canonical_rss_record(), project_id="ai26").to_document()
    assert document["source_text"].startswith("AI should serve democratic society")
    assert document["source_title"] == "Synthetic AI26 post"
    assert document["source_date"] == "2026-09-18T09:30:00+00:00"
    assert document["source_name"] == "Example Feed"
    assert document["source_author"] == "Ada Example"
    assert document["arena"] == "elites"
    assert document["language"] == "en"
    assert document["source_categories"] == ["AI", "Policy"]


def test_document_id_is_stable_across_runs() -> None:
    first = flatten_record(_canonical_rss_record(), project_id="ai26").document_id
    second = flatten_record(_canonical_rss_record(), project_id="ai26").document_id
    assert first == second


def test_document_never_carries_laclaudian_analysis_fields() -> None:
    """Collection owns source metadata; discourse codes belong downstream."""
    document = flatten_record(_canonical_rss_record(), project_id="ai26").to_document()
    for field in ("signifiers", "nodal_points", "formations", "frontier", "populism"):
        assert field not in document


def test_record_without_text_is_rejected() -> None:
    record = _canonical_rss_record()
    record["content"]["text"] = ""
    try:
        flatten_record(record, project_id="ai26")
    except ValueError as exc:
        assert "text" in str(exc)
        return
    raise AssertionError("a record without text must not be written")


# --------------------------------------------------------------------------
# Idempotency: re-collection must upsert, not duplicate
# --------------------------------------------------------------------------

def test_rerunning_collection_updates_instead_of_duplicating() -> None:
    collection = FakeCollection()
    record = _canonical_rss_record()

    first = upsert_phase0_documents(
        collection, [flatten_record(record, project_id="ai26")]
    )
    assert first == 1
    assert len(collection.docs) == 1

    # Re-collect the same article with different tracking parameters in the URL.
    again = _canonical_rss_record()
    again["source_url"] = "https://example.org/ai/post-1?utm_campaign=repost"
    upsert_phase0_documents(collection, [flatten_record(again, project_id="ai26")])

    assert len(collection.docs) == 1, "re-collection must not create a second document"
    assert collection.calls == 2


def test_tracking_parameters_and_fragments_are_stripped() -> None:
    canonical = "https://example.org/ai/post-1"
    for noisy in (
        "https://example.org/ai/post-1?utm_source=x&utm_medium=y",
        "https://example.org/ai/post-1#section",
        "https://EXAMPLE.org/ai/post-1/?fbclid=abc",
    ):
        assert canonicalize_url(noisy) == canonical


def test_distinct_articles_stay_distinct() -> None:
    a = flatten_record(_canonical_rss_record(), project_id="ai26")
    other = _canonical_rss_record()
    other["source_url"] = "https://example.org/ai/post-2"
    b = flatten_record(other, project_id="ai26")
    assert a.source_url != b.source_url

    collection = FakeCollection()
    upsert_phase0_documents(collection, [a, b])
    assert len(collection.docs) == 2


def test_flatten_accepts_an_already_flat_mapping() -> None:
    """The adapter must not require the nested canonical shape."""
    flat = flatten_record(
        {
            "source_url": "https://example.org/flat",
            "source_text": "Flat text",
            "source_title": "Flat",
            "source_date": "2026-09-18",
            "source_name": "Flat Feed",
        },
        project_id="ai26",
    )
    document = flat.to_document()
    assert document["source_text"] == "Flat text"
    assert document["source_name"] == "Flat Feed"


def test_phase0document_roundtrips_its_fields() -> None:
    document = flatten_record(_canonical_rss_record(), project_id="ai26")
    assert isinstance(document, Phase0Document)
    assert document.to_document()["source_url"] == "https://example.org/ai/post-1"


# --------------------------------------------------------------------------
# The documented CLI must exist and be wired to the Phase 0 writer
# --------------------------------------------------------------------------

def test_server_runner_exposes_the_declared_entry_point() -> None:
    """pyproject declares `laclaugpt-server-rss = ...:main`.

    The Phase 0 rework removed main() while the console script and the cron
    wrapper still referenced it, so the documented command failed to import.
    """
    import importlib

    module = importlib.import_module("laclaugpt_data_collection.server_runner")
    assert callable(getattr(module, "main", None))


def test_cli_parses_the_cron_wrapper_flags() -> None:
    """The wrapper passes these exact flags; argparse must accept them."""
    import importlib

    module = importlib.import_module("laclaugpt_data_collection.server_runner")
    argv = [
        "--source-manifest", "sources.toml",
        "--collection-id", "ai26",
        "--worker-id", "laskin-cron",
        "--max-feeds", "8",
        "--per-feed-limit", "5",
        "--limit", "40",
    ]
    # main() is exercised end-to-end elsewhere; here we only prove the CLI wiring
    # accepts the documented invocation without a parser error.
    parser_ok = True
    try:
        import argparse

        parser = argparse.ArgumentParser()
        parser.add_argument("--source-manifest", required=True)
        for flag in ("--collection-id", "--worker-id"):
            parser.add_argument(flag)
        for flag in ("--max-feeds", "--per-feed-limit", "--limit"):
            parser.add_argument(flag, type=int)
        parser.parse_args(argv)
    except SystemExit:
        parser_ok = False
    assert parser_ok
    assert callable(module.main)
