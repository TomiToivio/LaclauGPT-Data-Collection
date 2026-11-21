"""#442: the left-techno-optimism stratum needs an executable scholarly backend.

The stratum declares ``services = ["openalex", "semantic_scholar", "socArXiv"]``
and no backend existed for any of them, so its only configured source was
``active = false`` and collected 0 records in 14 attempts. OpenAlex is keyless,
so it is the cheap path to make the declared query executable.

These tests run entirely offline through the injectable client.
"""

from __future__ import annotations

from laclaugpt_data_collection.ai26_laskin_runner import preflight_optional_dependencies
from laclaugpt_data_collection.collectors.openalex import (
    OpenAlexCollector,
    _abstract_from_inverted_index,
    map_work,
)


def _work(**overrides):
    work = {
        "id": "https://openalex.org/W123456",
        "doi": "https://doi.org/10.1234/example",
        "title": "Postcapitalist automation and the democratic dividend",
        "publication_date": "2026-03-04",
        "publication_year": 2026,
        "type": "article",
        "language": "en",
        "authorships": [
            {"author": {"display_name": "A. Researcher"}},
            {"author": {"display_name": "B. Collaborator"}},
        ],
        "abstract_inverted_index": {
            "Automation": [0],
            "can": [1],
            "fund": [2],
            "redistribution.": [3],
        },
        "primary_location": {
            "landing_page_url": "https://example.org/article",
            "pdf_url": "https://example.org/article.pdf",
            "source": {"display_name": "Journal of Examples", "host_organization_name": "Example U"},
        },
        "cited_by_count": 7,
    }
    work.update(overrides)
    return work


def test_abstract_is_rebuilt_in_position_order():
    assert (
        _abstract_from_inverted_index({"b": [1], "a": [0], "c": [2]})
        == "a b c"
    )


def test_a_work_maps_to_a_canonical_record_with_its_source_text():
    record = map_work(_work())
    assert record is not None
    assert record.platform == "openalex"
    assert record.document_id == "W123456"
    assert record.source_url == "https://example.org/article"
    assert "Postcapitalist automation" in record.text
    assert "fund redistribution." in record.text
    assert record.author_fullname == "A. Researcher, B. Collaborator"
    assert record.collection_provenance.metadata["doi"] == "https://doi.org/10.1234/example"


def test_a_work_with_no_source_text_is_not_a_record():
    """No title and no abstract means nothing the evidence gate could ever code."""
    assert map_work(_work(title="", display_name="", abstract_inverted_index={})) is None


def test_collector_maps_results_and_reports_the_next_page():
    pages = {
        "1": {
            "meta": {"count": 120, "per_page": 50, "page": 1},
            "results": [
                _work(),
                _work(
                    id="https://openalex.org/W999",
                    doi="",
                    primary_location={"landing_page_url": "https://example.org/second"},
                ),
            ],
        }
    }

    def client(params):
        return pages[params["page"]]

    result = OpenAlexCollector("postcapitalism", max_results=50, client=client).collect()
    assert result.raw_items_seen == 2
    assert len(result.records) == 2
    assert result.next_cursor == "2", "a truncated page must offer the next page"


def test_last_page_does_not_offer_a_cursor():
    def client(params):
        return {"meta": {"count": 2, "per_page": 50, "page": 1}, "results": [_work()]}

    result = OpenAlexCollector("q", max_results=50, client=client).collect()
    assert result.next_cursor is None


def test_an_openalex_only_manifest_does_not_demand_the_arxiv_package():
    """Before #442 the preflight required 'documents' for every scholarly query."""
    jobs = [{"kind": "scholarly_query", "name": "left_techno_optimism",
             "services": ["openalex"]}]
    assert preflight_optional_dependencies(jobs) == []
