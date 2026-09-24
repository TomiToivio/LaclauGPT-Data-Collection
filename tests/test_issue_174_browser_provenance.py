from __future__ import annotations

from laclaugpt_data_collection.normalize import normalise


def test_browser_normalisation_preserves_study_identity_in_provenance() -> None:
    record = normalise(
        "x",
        {"id": "1", "link": "https://x.example.invalid/status/1"},
        metadata={
            "project_id": "brazil26",
            "collection_id": "brazil26",
            "study": "brazil-presidential-2026",
        },
    )

    assert record.provenance[0].metadata == {
        "project_id": "brazil26",
        "collection_id": "brazil26",
        "study": "brazil-presidential-2026",
    }