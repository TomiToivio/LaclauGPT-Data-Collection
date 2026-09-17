from laclaugpt_data_collection.acdt_compat import (
    export_legacy_row,
    import_legacy_manifesto,
    import_legacy_twitter,
)


def test_twitter_legacy_round_trip_preserves_source_relations_and_unknown_fields():
    row = {
        "tweet_id": "123",
        "user_id": "actor-7",
        "username": "research_actor",
        "timestamp": "2021-02-03T10:00:00Z",
        "text": "Masks now #maskit",
        "hashtags": ["maskit"],
        "mentions": ["THLorg"],
        "urls": ["https://example.org/evidence"],
        "reply_to_id": "122",
        "reply_to_actor": "another_actor",
        "media": [
            {
                "type": "image",
                "url": "https://example.org/image.jpg",
                "timestamp_seconds": 1.5,
            }
        ],
        "translated_text": "Masks now",
        "translation_metadata": {"provider": "synthetic", "source_language": "fi"},
        "custom_legacy_column": "must-survive",
    }
    record = import_legacy_twitter(row, study_id="covid-fi")

    assert record.source_url == "x:123"
    assert record.source_native_ids["actor_id"] == "actor-7"
    assert record.source.raw_metadata["hashtags"] == ["maskit"]
    assert record.source.raw_metadata["interaction_ids"]["parent_document_id"] == "122"
    assert record.source.raw_metadata["interaction_ids"]["reply_to_actor"] == "another_actor"
    assert record.content.media_references[0].metadata["timestamp_seconds"] == 1.5
    assert record.source.raw_metadata["translation_metadata"]["provider"] == "synthetic"
    assert "ideology" not in record.source.raw_metadata

    exported = export_legacy_row(record)
    assert exported["custom_legacy_column"] == "must-survive"
    assert exported["hashtags"] == ["maskit"]
    assert exported["mentions"] == ["THLorg"]
    assert exported["media_references"][0]["metadata"]["timestamp_seconds"] == 1.5
    assert exported["translation_metadata"]["source_language"] == "fi"


def test_manifesto_legacy_round_trip_preserves_measurement_columns():
    row = {
        "manifesto_id": "fi-2019-party-a",
        "party": "Party A",
        "date": "2019-04-01",
        "language": "fi",
        "text": "Manifesto text",
        "wordscores_lr": -0.42,
        "emotion_joy": 0.31,
    }
    record = import_legacy_manifesto(row, study_id="manifestos-fi")
    exported = export_legacy_row(record)

    assert exported["wordscores_lr"] == -0.42
    assert exported["emotion_joy"] == 0.31
    assert exported["text"] == "Manifesto text"
    assert record.legacy["original"]["wordscores_lr"] == -0.42
