from pathlib import Path

from laclaugpt_data_collection.kg import (
    SQLiteKGStore,
    project_record,
    serialize_rdf,
    stable_uri,
    to_arango_documents,
    to_jsonld,
    to_mongo_graph_documents,
    write_csv_tables,
)
from laclaugpt_data_collection.models import (
    CanonicalRecord,
    CollectionProvenance,
    ContentSection,
    MediaReference,
    RawCaptureSection,
    SourceSection,
)


def sample_record() -> CanonicalRecord:
    return CanonicalRecord(
        source_url="https://example.invalid/post/42?utm_source=test",
        source_native_ids={"post_id": "42"},
        raw_capture=RawCaptureSection(
            ref="s3://synthetic/raw/42.json",
            checksum="sha256:raw",
            content_type="application/json",
        ),
        source=SourceSection(
            platform="synthetic",
            source_type="post",
            author="acct-7",
            author_fullname="Synthetic Author",
            created_at="2026-09-19T10:00:00Z",
            collected_at="2026-09-19T10:00:03Z",
            parent_source_url="https://example.invalid/post/41",
            language="en",
        ),
        content=ContentSection(
            title="Synthetic record",
            text="synthetic",
            media_references=[
                MediaReference(
                    kind="video",
                    media_type="video/mp4",
                    object_ref="s3://synthetic/media/42.mp4",
                    checksum="sha256:media",
                )
            ],
        ),
        provenance=[
            CollectionProvenance(
                provenance_id="prov-42",
                collector="synthetic-collector",
                collector_version="1.2.3",
                captured_at="2026-09-19T10:00:03Z",
                method="fixture",
                input_refs=["fixture://request/42"],
            )
        ],
    )


def test_stable_uri_is_backend_independent() -> None:
    left = stable_uri("document", "https://example.invalid/post/42")
    right = stable_uri("document", "https://example.invalid/post/42")
    assert left == right
    assert "ObjectId" not in left


def test_projection_preserves_identity_across_backends(tmp_path: Path) -> None:
    record = sample_record()
    projection = project_record(record, study_id="AI26")
    document_id = stable_uri("document", record.source_url)

    assert document_id in projection.node_map()
    assert any(edge.type == "schema:author" for edge in projection.edges)
    assert any(edge.type == "prov:wasGeneratedBy" for edge in projection.edges)
    assert any(edge.type == "laclau:repliesTo" for edge in projection.edges)

    mongo = to_mongo_graph_documents(projection)
    arango = to_arango_documents(projection)
    assert any(item["semantic_id"] == document_id for item in mongo["entities"])
    assert any(item["semantic_id"] == document_id for item in arango["vertices"])

    nodes_path, edges_path = write_csv_tables(tmp_path / "csv", projection)
    assert nodes_path.is_file()
    assert edges_path.is_file()

    sqlite_path = tmp_path / "kg.sqlite3"
    SQLiteKGStore(sqlite_path).write(projection)
    assert sqlite_path.is_file()


def test_jsonld_and_rdf_are_valid_and_traceable() -> None:
    record = sample_record()
    projection = project_record(record, study_id="AI26")
    document_id = stable_uri("document", record.source_url)
    jsonld = to_jsonld(projection)

    assert jsonld["@context"]["prov"] == "http://www.w3.org/ns/prov#"
    assert any(item.get("id") == document_id for item in jsonld["@graph"])

    turtle = serialize_rdf(projection, format="turtle")
    assert document_id in turtle
    nquads = serialize_rdf(projection, format="nquads")
    assert document_id in nquads


def test_shacl_fixture_validates() -> None:
    from pyshacl import validate

    data_graph = serialize_rdf(project_record(sample_record(), study_id="AI26"), format="turtle")
    shapes = Path("schemas/collection-shapes.ttl").read_text(encoding="utf-8")
    conforms, _, report = validate(
        data_graph=data_graph,
        data_graph_format="turtle",
        shacl_graph=shapes,
        shacl_graph_format="turtle",
    )
    assert conforms, str(report)
