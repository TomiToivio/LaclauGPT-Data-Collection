"""arXiv search adapter with optional PDF references.

Reimplemented from CyborgAnthropology around the canonical Collection record.
"""
from __future__ import annotations

from typing import Any

from ..models import CollectionProvenance, MediaReference, NormalizedRecord
from .base import CollectionResult


def _paper_snapshot(paper: Any) -> dict[str, Any]:
    """Return a deterministic, JSON-safe bibliographic snapshot for raw preservation."""
    authors = [str(getattr(author, "name", author)) for author in (getattr(paper, "authors", None) or [])]
    categories = [str(value) for value in (getattr(paper, "categories", None) or [])]
    published = getattr(paper, "published", None)
    updated = getattr(paper, "updated", None)
    return {
        "entry_id": str(getattr(paper, "entry_id", "") or ""),
        "title": str(getattr(paper, "title", "") or ""),
        "summary": str(getattr(paper, "summary", "") or ""),
        "authors": authors,
        "categories": categories,
        "primary_category": str(getattr(paper, "primary_category", "") or ""),
        "published": published.isoformat() if hasattr(published, "isoformat") else str(published or ""),
        "updated": updated.isoformat() if hasattr(updated, "isoformat") else str(updated or ""),
        "pdf_url": str(getattr(paper, "pdf_url", "") or ""),
    }


def map_paper(paper: Any) -> NormalizedRecord | None:
    snapshot = _paper_snapshot(paper)
    entry_id = snapshot["entry_id"]
    if not entry_id:
        return None
    paper_id = entry_id.rstrip("/").rsplit("/", 1)[-1]
    source_url = f"https://arxiv.org/abs/{paper_id}"
    authors = snapshot["authors"]
    categories = snapshot["categories"]
    pdf_url = snapshot["pdf_url"]
    media = (
        [
            MediaReference(
                kind="pdf",
                media_type="application/pdf",
                url=pdf_url,
                metadata={"download_required": True, "source": "arxiv"},
            )
        ]
        if pdf_url
        else []
    )
    text = "\n\n".join(part for part in [snapshot["title"], snapshot["summary"]] if part)
    record = NormalizedRecord(
        document_id=paper_id,
        platform="arxiv",
        author=authors[0] if authors else "",
        author_fullname=", ".join(authors),
        timestamp=snapshot["published"],
        source_url=source_url,
        text=text,
        media_references=media,
        raw_payload=snapshot,
        raw_content_type="application/vnd.arxiv.metadata+json",
        collection_provenance=CollectionProvenance(
            module="arxiv-client",
            visited_url=source_url,
            api_url=entry_id,
            transformations=["arxiv-result", "map-paper"],
            metadata={
                "authors": authors,
                "categories": categories,
                "primary_category": snapshot["primary_category"],
                "updated": snapshot["updated"],
                "pdf_url": pdf_url,
            },
        ),
    )
    record.content.title = snapshot["title"] or None
    return record


class ArxivCollector:
    def __init__(
        self,
        query: str,
        *,
        max_results: int = 10,
        categories: list[str] | None = None,
        cursor: str | None = None,
        client: Any | None = None,
    ) -> None:
        if max_results < 1:
            raise ValueError("max_results must be at least 1")
        self.query = query
        self.max_results = max_results
        self.categories = categories or []
        self.cursor = cursor
        self.client = client

    @property
    def offset(self) -> int:
        if self.cursor in (None, ""):
            return 0
        try:
            value = int(str(self.cursor))
        except ValueError as exc:
            raise ValueError("arxiv cursor must be a non-negative integer offset") from exc
        if value < 0:
            raise ValueError("arxiv cursor must be a non-negative integer offset")
        return value

    def _query(self) -> str:
        query = f"all:{self.query}"
        if self.categories:
            query += " AND (" + " OR ".join(f"cat:{cat}" for cat in self.categories) + ")"
        return query

    def _search(self) -> list[Any]:
        query = self._query()
        offset = self.offset
        if self.client is not None:
            try:
                return list(
                    self.client(
                        query=query,
                        max_results=self.max_results,
                        offset=offset,
                    )
                )
            except TypeError:
                # Backward compatibility for simple injected clients used by older callers/tests.
                rows = list(self.client(query=query, max_results=self.max_results + offset))
                return rows[offset : offset + self.max_results]
        try:
            import arxiv
        except ImportError as exc:
            raise RuntimeError("Install the 'documents' extra for arXiv support") from exc
        search = arxiv.Search(
            query=query,
            max_results=self.max_results,
            sort_by=arxiv.SortCriterion.SubmittedDate,
        )
        return list(arxiv.Client().results(search, offset=offset))

    def collect(self) -> CollectionResult:
        result = CollectionResult(requests_seen=1)
        rows = self._search()
        result.bodies_seen = 1
        result.raw_items_seen = len(rows)
        seen: set[str] = set()
        for paper in rows:
            record = map_paper(paper)
            if record and record.source_url not in seen:
                seen.add(record.source_url)
                result.records.append(record)
        if len(rows) >= self.max_results:
            result.next_cursor = str(self.offset + len(rows))
        if not result.records:
            result.warnings.append(result.zero_result_warning or "No arXiv papers collected")
        return result
