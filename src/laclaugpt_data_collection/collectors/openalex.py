"""OpenAlex search adapter (#442).

The `left_techno_optimism` stratum declared `services = ["openalex",
"semantic_scholar", "socArxiv"]` and no backend existed for any of them, so the
only configured source for left-wing and postcapitalist techno-optimism could
never collect a record. OpenAlex is the cheap way to make the declared query
executable: it needs no key and no new dependency, so this adapter is stdlib
HTTP plus the same canonical record mapping the arXiv adapter uses.

API: https://docs.openalex.org/api-entities/works/search-works
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any

from ..models import CollectionProvenance, NormalizedRecord
from .base import CollectionResult

DEFAULT_ENDPOINT = "https://api.openalex.org/works"


def _abstract_from_inverted_index(index: Any) -> str:
    """Rebuild the abstract text from OpenAlex's inverted index.

    OpenAlex stores ``{"word": [position, ...]}`` to avoid redistributing the
    publisher's prose verbatim. Reconstructing it is the documented way to read
    the abstract, and without it the record would carry only a title -- which is
    not enough source text to analyse.
    """
    if not isinstance(index, dict) or not index:
        return ""
    placed: list[tuple[int, str]] = []
    for word, positions in index.items():
        for position in positions or []:
            if isinstance(position, int):
                placed.append((position, str(word)))
    placed.sort()
    return " ".join(word for _, word in placed)


def _authors(work: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for authorship in work.get("authorships") or []:
        author = authorship.get("author") or {}
        name = str(author.get("display_name") or "").strip()
        if name and name not in names:
            names.append(name)
    return names


def work_snapshot(work: dict[str, Any]) -> dict[str, Any]:
    """A deterministic, JSON-safe bibliographic snapshot for raw preservation."""
    location = work.get("primary_location") or {}
    source = location.get("source") or {}
    return {
        "id": str(work.get("id") or ""),
        "doi": str(work.get("doi") or ""),
        "title": str(work.get("title") or work.get("display_name") or ""),
        "publication_date": str(work.get("publication_date") or ""),
        "publication_year": work.get("publication_year"),
        "type": str(work.get("type") or ""),
        "language": str(work.get("language") or ""),
        "authors": _authors(work),
        "abstract": _abstract_from_inverted_index(work.get("abstract_inverted_index")),
        "landing_page_url": str(location.get("landing_page_url") or ""),
        "pdf_url": str(location.get("pdf_url") or ""),
        "host_venue": str(source.get("display_name") or ""),
        "host_organization": str(source.get("host_organization_name") or ""),
        "cited_by_count": work.get("cited_by_count"),
    }


def map_work(work: dict[str, Any]) -> NormalizedRecord | None:
    snapshot = work_snapshot(work)
    openalex_id = snapshot["id"].rstrip("/").rsplit("/", 1)[-1]
    if not openalex_id:
        return None
    source_url = snapshot["landing_page_url"] or f"https://openalex.org/{openalex_id}"
    title, abstract = snapshot["title"], snapshot["abstract"]
    text = "\n\n".join(part for part in (title, abstract) if part)
    if not text:
        # A work with neither a title nor an abstract carries no source text; the
        # AI26 evidence gate cannot code it, so it is not a usable record.
        return None

    from ..language import resolve_language

    language, method = resolve_language(text) if not snapshot["language"] else (
        snapshot["language"],
        "openalex",
    )
    authors = snapshot["authors"]
    record = NormalizedRecord(
        document_id=openalex_id,
        language=language,
        platform="openalex",
        author=authors[0] if authors else "",
        author_fullname=", ".join(authors),
        timestamp=snapshot["publication_date"],
        source_url=source_url,
        text=text,
        raw_payload=snapshot,
        raw_content_type="application/vnd.openalex.work+json",
        collection_provenance=CollectionProvenance(
            module="openalex-client",
            visited_url=source_url,
            api_url=snapshot["id"],
            transformations=["openalex-work", "map-work"],
            metadata={
                "authors": authors,
                "doi": snapshot["doi"],
                "type": snapshot["type"],
                "host_venue": snapshot["host_venue"],
                "host_organization": snapshot["host_organization"],
                "cited_by_count": snapshot["cited_by_count"],
                "language_method": method,
            },
        ),
    )
    record.content.title = title or None
    return record


class OpenAlexCollector:
    """Search OpenAlex works and map them to canonical records.

    ``client`` is injectable so tests never touch the network; it receives the
    query parameters and returns the decoded JSON body.
    """

    def __init__(
        self,
        query: str,
        *,
        max_results: int = 50,
        cursor: str | None = None,
        endpoint: str = DEFAULT_ENDPOINT,
        mailto: str | None = None,
        client: Any | None = None,
    ) -> None:
        if max_results < 1:
            raise ValueError("max_results must be at least 1")
        self.query = query.strip()
        self.max_results = max_results
        self.cursor = cursor
        self.endpoint = endpoint
        self.mailto = mailto
        self.client = client

    @property
    def page(self) -> int:
        if self.cursor in (None, ""):
            return 1
        try:
            value = int(str(self.cursor))
        except ValueError as exc:
            raise ValueError("openalex cursor must be a positive page number") from exc
        if value < 1:
            raise ValueError("openalex cursor must be a positive page number")
        return value

    def _params(self) -> dict[str, str]:
        if not self.query:
            raise ValueError("openalex query must not be empty")
        params = {
            "search": self.query,
            "per-page": str(min(self.max_results, 200)),
            "page": str(self.page),
            "sort": "publication_date:desc",
        }
        if self.mailto:
            # OpenAlex asks API users to identify themselves; it is not a key.
            params["mailto"] = self.mailto
        return params

    def _fetch(self, params: dict[str, str]) -> dict[str, Any]:
        if self.client is not None:
            body = self.client(params)
            if isinstance(body, (str, bytes)):
                return json.loads(body)
            return body
        url = f"{self.endpoint}?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(url, headers={"User-Agent": "laclaugpt-data-collection"})
        with urllib.request.urlopen(request, timeout=45) as response:  # noqa: S310 - fixed https endpoint
            return json.loads(response.read().decode("utf-8"))

    def collect(self) -> CollectionResult:
        result = CollectionResult(requests_seen=1)
        body = self._fetch(self._params())
        result.bodies_seen = 1
        works = body.get("results") or []
        result.raw_items_seen = len(works)
        seen: set[str] = set()
        for work in works:
            record = map_work(work)
            if record and record.source_url not in seen:
                seen.add(record.source_url)
                result.records.append(record)
        meta = body.get("meta") or {}
        count, per_page = meta.get("count"), meta.get("per_page")
        if (
            isinstance(count, int)
            and isinstance(per_page, int)
            and per_page > 0
            and self.page * per_page < count
        ):
            result.next_cursor = str(self.page + 1)
        if not result.records:
            result.warnings.append(result.zero_result_warning or "No OpenAlex works collected")
        return result
