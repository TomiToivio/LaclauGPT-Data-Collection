from laclaugpt_data_collection.models import CanonicalRecord, SourceLocation, SourceSection


def test_source_provided_location_round_trips_without_inference() -> None:
    record = CanonicalRecord(
        source_url="https://example.invalid/post/1",
        source=SourceSection(
            platform="synthetic",
            locations=[
                SourceLocation(
                    name="Helsinki",
                    country="Finland",
                    latitude=60.1699,
                    longitude=24.9384,
                    source_field="place",
                    metadata={"provenance": "source-provided"},
                )
            ],
        ),
    )

    restored = CanonicalRecord.model_validate(record.model_dump(mode="json"))
    location = restored.source.locations[0]
    assert location.name == "Helsinki"
    assert location.country == "Finland"
    assert location.latitude == 60.1699
    assert location.longitude == 24.9384
    assert location.source_field == "place"
    assert location.metadata["provenance"] == "source-provided"


def test_source_location_is_optional_for_text_only_records() -> None:
    record = CanonicalRecord(source_url="urn:synthetic:1")
    assert record.source.locations == []
