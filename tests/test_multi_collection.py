from pathlib import Path

from laclaugpt_data_collection.multi_capture_server import (
    MultiCollectionStore,
    collection_id_for,
    matching_targets,
)
from laclaugpt_data_collection.study import StudyConfig


def config(study: str, handle: str, *, arena: str = "") -> StudyConfig:
    return StudyConfig(
        {
            "study": study,
            "window": {"start": "2026-01-01", "end": "2026-12-31"},
            "timezone": "UTC",
            "platforms": {
                "x": {
                    "enabled": True,
                    "base_urls": ["https://x.com/{handle}"],
                }
            },
            "groups": [
                {
                    "id": f"{study}-group",
                    "name": study,
                    "arena": arena,
                    "accounts": {"x": [handle]},
                }
            ],
        },
        f"{study}.yaml",
    )


def record(collection_id: str, source_url: str) -> dict:
    return {
        "collection_id": collection_id,
        "source_url": source_url,
        "source": {"platform": "x"},
        "content": {"text": "synthetic"},
    }


def test_matching_targets_routes_same_port_by_configured_account() -> None:
    ai26 = config("ai26", "ai_researcher", arena="elites")
    brazil26 = config("brazil26", "br_candidate", arena="parliamentary")
    matches = matching_targets(
        [ai26, brazil26],
        "x",
        "https://x.com/br_candidate/status/123",
    )
    assert len(matches) == 1
    selected, account = matches[0]
    assert collection_id_for(selected) == "brazil26"
    assert account is not None
    assert account["arena"] == "parliamentary"


def test_unattributed_capture_is_not_guessed_with_multiple_collections() -> None:
    ai26 = config("ai26", "ai_researcher")
    brazil26 = config("brazil26", "br_candidate")
    assert matching_targets([ai26, brazil26], "x", "https://x.com/unknown/status/1") == []


def test_single_collection_keeps_legacy_unattributed_fallback() -> None:
    ai26 = config("ai26", "ai_researcher")
    matches = matching_targets([ai26], "x", "https://x.com/unknown/status/1")
    assert matches == [(ai26, None)]


def test_same_source_url_can_exist_in_two_collections(tmp_path: Path) -> None:
    store = MultiCollectionStore(tmp_path)
    try:
        source_url = "https://x.com/shared/status/42"
        assert store.upsert_post(record("ai26", source_url), "raw/a.ndjson") is True
        assert store.upsert_post(record("brazil26", source_url), "raw/b.ndjson") is True
        assert store.upsert_post(record("ai26", source_url), "raw/c.ndjson") is False
        rows = (tmp_path / "normalized" / "x.jsonl").read_text(encoding="utf-8").splitlines()
        assert len(rows) == 2
        assert store.seen_count() == 2
    finally:
        store.close()
