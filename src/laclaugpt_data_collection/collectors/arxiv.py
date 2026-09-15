"""arXiv search adapter with optional PDF references.

Reimplemented from CyborgAnthropology around the canonical Collection record.
"""
from __future__ import annotations

from typing import Any

from ..models import CollectionProvenance, MediaReference, NormalizedRecord
from .base import CollectionResult


def map_paper(paper: Any) -> NormalizedRecord | None:
    entry_id = str(getattr(paper, "entry_id", "") or "")
    if not entry_id:
        return None
    paper_id = entry_id.rstrip("/").rsplit("/", 1)[-1]
    source_url = f"https://arxiv.org/abs/{paper_id}"
    published = getattr(paper, "published", None)
    created_at = published.isoformat() if hasattr(published, "isoformat") else str(published or "")
    authors = [str(getattr(author, "name", author)) for author in (getattr(paper, "authors", None) or [])]
    categories = [str(value) for value in (getattr(paper, "categories", None) or [])]
    pdf_url = str(getattr(paper, "pdf_url", "") or "")
    media = [MediaReference(kind="pdf", url=pdf_url)] if pdf_url else []
    text = "\n\n".join(part for part in [str(getattr(paper, "title", "") or ""), str(getattr(paper, "summary", "") or "")] if part)
    return NormalizedRecord(
        document_id=paper_id,
        platform="arxiv",
        author=authors[0] if authors else "",
        author_fullname=", ".join(authors),
        timestamp=created_at,
        source_url=source_url,
        text=text,
        media_references=media,
        collection_provenance=CollectionProvenance(
            module="arxiv-client",
            visited_url=source_url,
            api_url=entry_id,
            transformations=["arxiv-result", "map-paper"],
            metadata={
                "authors": authors,
                "categories": categories,
                "primary_category": getattr(paper, "primary_category", None),
                "updated": getattr(getattr(paper, "updated", None), "isoformat", lambda: "")(),
                "pdf_url": pdf_url,
            },
        ),
    )


class ArxivCollector:
    def __init__(self, query: str, *, max_results: int = 10, categories: list[str] | None = None, client: Any | None = None) -> None:
        self.query = query
        self.max_results = max_results
        self.categories = categories or []
        self.client = client

    def _search(self) -> list[Any]:
        query = f"all:{self.query}"
        if self.categories:
            query += " AND (" + " OR ".join(f"cat:{cat}" for cat in self.categories) + ")"
        if self.client is not None:
            return list(self.client(query=query, max_results=self.max_results))
        try:
            import arxiv
        except ImportError as exc:
            raise RuntimeError("Install the 'documents' extra for arXiv support") from exc
        search = arxiv.Search(query=query, max_results=self.max_results, sort_by=arxiv.SortCriterion.SubmittedDate)
        return list(arxiv.Client().results(search))

    def collect(self) -> CollectionResult:
        result = CollectionResult(requests_seen=1)
        rows = self._search()
        result.bodies_seen = 1
        result.raw_items_seen = len(rows)
        for paper in rows:
            record = map_paper(paper)
            if record:
                result.records.append(record)
        if not result.records:
            result.warnings.append(result.zero_result_warning or "No arXiv papers collected")
        return result
