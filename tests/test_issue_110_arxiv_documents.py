import json
from pathlib import Path
from types import SimpleNamespace

from laclaugpt_data_collection import handoff, plugins
from laclaugpt_data_collection.collectors import arxiv, documents

FIXTURE = Path(__file__).parent / "fixtures" / "phase1_arxiv_document.json"


def _paper_from_fixture() -> SimpleNamespace:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return SimpleNamespace(
        entry_id=data["entry_id"],
        title=data["title"],
        summary=data["summary"],
        authors=[SimpleNamespace(name=name) for name in data["authors"]],
        categories=data["categories"],
        primary_category=data["primary_category"],
        published=data["published"],
        updated=data["updated"],
        pdf_url=data["pdf_url"],
    )


def test_arxiv_fixture_maps_to_canonical_document_and_analysis_handoff() -> None:
    record = arxiv.map_paper(_paper_from_fixture())
    assert record is not None
    assert record.source_url == "https://arxiv.org/abs/2609.12345"
    assert record.document_id == "2609.12345"
    assert record.content.title == "Synthetic Phase 1 arXiv paper"
    assert record.raw_capture.preserved is True
    assert record.raw_capture.payload["primary_category"] == "cs.AI"
    assert record.media_references[0].url == "https://arxiv.org/pdf/2609.12345"
    assert record.media_references[0].metadata["download_required"] is True

    result_handoff = handoff.build_handoff(record.model_dump(mode="json"), project_id="synthetic")
    assert result_handoff["source_url"] == record.source_url
    assert result_handoff["status"] == "waiting_media"


def test_arxiv_cursor_pagination_and_batch_dedup_are_deterministic() -> None:
    observed: dict[str, object] = {}

    def client(*, query: str, max_results: int, offset: int):
        observed.update(query=query, max_results=max_results, offset=offset)
        paper = _paper_from_fixture()
        return [paper, paper]

    result = arxiv.ArxivCollector(
        "synthetic AI",
        max_results=2,
        categories=["cs.AI"],
        cursor="20",
        client=client,
    ).collect()

    assert observed == {
        "query": "all:synthetic AI AND (cat:cs.AI)",
        "max_results": 2,
        "offset": 20,
    }
    assert [record.source_url for record in result.records] == [
        "https://arxiv.org/abs/2609.12345"
    ]
    assert result.next_cursor == "22"


def test_arxiv_invalid_cursor_fails_explicitly() -> None:
    collector = arxiv.ArxivCollector("synthetic", cursor="not-an-offset", client=lambda **_: [])
    try:
        collector.collect()
    except ValueError as exc:
        assert "non-negative integer offset" in str(exc)
    else:
        raise AssertionError("invalid arXiv cursor should fail")


def test_local_document_is_content_addressed_without_absolute_path(tmp_path: Path) -> None:
    source = tmp_path / "synthetic.txt"
    source.write_text("Synthetic local research document.", encoding="utf-8")

    record = documents.extract_document(source)

    assert record.source_url.startswith("file+sha256:")
    assert record.raw_ref == record.source_url
    assert record.raw_capture.checksum == record.document_id
    assert record.content.title == "synthetic.txt"
    assert record.content.file_references[0]["ref"] == record.source_url
    assert str(tmp_path) not in json.dumps(record.model_dump(mode="json"))
    assert (
        record.provenance[0].metadata["raw_reference_policy"]
        == "content-addressed-local-reference; absolute paths are not persisted"
    )


def test_phase1_registry_declares_arxiv_contract() -> None:
    spec = {item.plugin_id: item for item in plugins.default_registry().specs()}["arxiv"]
    assert spec.source_type == "scholarly_document"
    assert "query" in spec.config_schema["required"]
    assert spec.canonical_identifier == "canonical https://arxiv.org/abs/<id> URL"
