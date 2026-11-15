"""Fetch the article body for RSS items whose feed syndicates only a headline (#416).

A third of the ready RSS stratum carried a headline and nothing else: `tech_policy_press` stored
87-character "texts" for 196 of 196 records, `openai_news` 118 of 118, `datacenterdynamics` 141 of 142.
The collector is not at fault — those feeds publish `<title>` and no `<description>` or
`<content:encoded>`, verified against the live feeds — and the web path in the same corpus stores whole
documents (mean ~128,000 characters over 263 records). The difference is that something asked the
article page for its body.

So this asks. For a record whose stored text is shorter than a usable analysis unit, fetch the article
URL with the same guarded fetcher the web collector uses (host validation, redirect limit, content-type
allowlist, size cap), extract the visible text, and keep the result **with its own provenance**: the
enrichment is a fetch, and a reader must be able to see that the body did not come from the feed.

Two decisions worth stating:

* **A patch, not a new record.** The canonical record keeps its identity, source URL, handoff and
  collection provenance. What changes is `content.text` (longer), `human_readable` (regenerated from it)
  and one appended provenance entry naming `rss-body-enrichment`.
* **No silent wins.** A fetch that returns less than `MIN_GAIN_FACTOR` times the stored text, or fewer
  than `MIN_GAIN_CHARS` characters, is recorded as `skipped` rather than applied — otherwise a cookie
  banner counts as an article and the corpus fills with boilerplate.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable, Iterable, Mapping, Sequence
from urllib.parse import urlsplit

#: The threshold the #416 measurement used: below this, a "text" is a headline.
SHORT_TEXT_CHARS = 300

#: Provenance markers. Idempotence depends on the transformation name, not on a side table.
ENRICHMENT_TRANSFORM = "rss-body-enrichment"
ENRICHMENT_MODULE = "external-link-fetcher"

#: A body must be at least this many times longer and this many characters bigger to count.
MIN_GAIN_FACTOR = 2.0
MIN_GAIN_CHARS = 300

#: Platform value that means "this came from an RSS/Atom feed".
RSS_PLATFORMS = frozenset({"rss", "atom"})

Fetch = Callable[[str], "tuple[str, str] | None"]


def stored_text(record: Mapping[str, Any]) -> str:
    content = record.get("content") or {}
    if isinstance(content, Mapping):
        return str(content.get("text") or "")
    return ""


def source_url(record: Mapping[str, Any]) -> str:
    return str(record.get("source_url") or "")


def already_enriched(record: Mapping[str, Any]) -> bool:
    for entry in record.get("provenance") or []:
        if isinstance(entry, Mapping) and ENRICHMENT_TRANSFORM in (entry.get("transformations") or []):
            return True
    return False


def needs_enrichment(record: Mapping[str, Any], *, max_chars: int = SHORT_TEXT_CHARS) -> bool:
    """True when this record is a short, fetchable, not-yet-enriched RSS item."""
    if record.get("project_id") and str(record.get("project_id")) != "ai26":
        return False
    handoff = record.get("handoff") or {}
    if handoff.get("status") and str(handoff.get("status")) != "ready":
        return False
    platform = str((record.get("source") or {}).get("platform") or "").casefold()
    if platform not in RSS_PLATFORMS:
        return False
    if len(stored_text(record).strip()) >= max_chars:
        return False
    url = source_url(record)
    if urlsplit(url).scheme not in {"http", "https"}:
        return False
    return not already_enriched(record)


def is_useful_gain(before: int, after: int) -> bool:
    """Guard against replacing a headline with a cookie banner."""
    return after >= MIN_GAIN_CHARS and after >= before * MIN_GAIN_FACTOR


def extract_body_text(html: str) -> str:
    """Visible text of an article page, preferring readability when it is installed.

    The fetcher's own `_html_text` is a regex that keeps `<style>` blocks and the document title —
    fine for "is there something here", wrong for the analysis unit, where CSS would be counted as
    the article's first 400 characters. `extract_visible_text` skips script/style/noscript; when
    `readability-lxml` is available it strips navigation and chrome as well.
    """
    from .extraction.html import extract_visible_text, extract_with_readability

    try:
        return extract_with_readability(html).text
    except RuntimeError:
        return extract_visible_text(html).text


@dataclass(frozen=True)
class EnrichmentResult:
    url: str
    status: str  # enriched | skipped | failed | not_needed
    chars_before: int
    chars_after: int = 0
    detail: str = ""
    final_url: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "status": self.status,
            "chars_before": self.chars_before,
            "chars_after": self.chars_after,
            "detail": self.detail,
            "final_url": self.final_url,
        }


def enrichment_provenance(*, final_url: str, visited_url: str, fetched_at: str, chars: int) -> dict[str, Any]:
    """The provenance entry that makes the enrichment visible and idempotent."""
    return {
        "provenance_id": "",
        "stage": "collection",
        "collector": "laclaugpt-data-collection",
        "collector_version": "0.1.0",
        "captured_at": fetched_at,
        "created_at": None,
        "capture_id": "",
        "run_id": "",
        "method": "article-body-fetch",
        "module": ENRICHMENT_MODULE,
        "module_version": "",
        "git_commit": "",
        "model": None,
        "model_version": None,
        "visited_url": visited_url,
        "api_url": final_url,
        "input_refs": [visited_url],
        "transformations": [ENRICHMENT_TRANSFORM],
        "metadata": {
            "chars_stored": chars,
            "reason": "feed syndicated no article body (#416)",
        },
    }


def build_patch(
    record: Mapping[str, Any],
    *,
    body_text: str,
    final_url: str,
    fetched_at: str,
) -> dict[str, Any]:
    """The MongoDB update document for one enriched record. Pure, so the tests can inspect it."""
    url = source_url(record)
    text = body_text.strip()
    provenance = list(record.get("provenance") or [])
    provenance.append(
        enrichment_provenance(final_url=final_url, visited_url=url, fetched_at=fetched_at, chars=len(text))
    )
    human_readable = dict(record.get("human_readable") or {})
    # The collection-stage summary is derived from content.text; keep it derived rather than stale.
    human_readable["summary"] = text[:500] + ("…" if len(text) > 500 else "")
    human_readable["generated_at"] = fetched_at
    patch: dict[str, Any] = {
        "content.text": text,
        "human_readable.summary": human_readable["summary"],
        "human_readable.generated_at": human_readable["generated_at"],
        "provenance": provenance,
        "updated_at": fetched_at,
    }

    # #423: the body is precisely the evidence a language label needs. A record enriched from a
    # headline keeps its blank `source.language` otherwise, so the arena x language cells stay
    # computed over indeterminate cases even though the material to resolve them is now stored.
    # Existing labels are never overwritten, and an unknown answer stays blank with its reason.
    source = dict(record.get("source") or {})
    if not str(source.get("language") or "").strip():
        from .language import resolve_language

        tag, method = resolve_language(text)
        raw_metadata = dict(source.get("raw_metadata") or {})
        raw_metadata["language_method"] = method
        raw_metadata["language_backfill"] = ""
        patch["source.raw_metadata"] = raw_metadata
        if tag:
            patch["source.language"] = tag
    return patch


def enrich_record(
    record: Mapping[str, Any],
    *,
    fetch: Fetch,
    now: Callable[[], str] | None = None,
    max_chars: int = SHORT_TEXT_CHARS,
) -> tuple[EnrichmentResult, dict[str, Any] | None]:
    """Fetch and decide. Returns the result and the patch to apply (or None)."""
    stamp = (now or (lambda: datetime.now(UTC).isoformat()))()
    url = source_url(record)
    before = len(stored_text(record).strip())
    if not needs_enrichment(record, max_chars=max_chars):
        return (EnrichmentResult(url, "not_needed", before, detail="stored text is long enough"), None)
    fetched = fetch(url)
    if not fetched:
        return (EnrichmentResult(url, "failed", before, detail="fetch returned nothing"), None)
    final_url, html = fetched
    body = extract_body_text(html or "")
    after = len(body.strip())
    if not is_useful_gain(before, after):
        return (
            EnrichmentResult(
                url,
                "skipped",
                before,
                after,
                detail=f"gain too small (needed >= {MIN_GAIN_CHARS} chars and >= {MIN_GAIN_FACTOR}x)",
                final_url=final_url,
            ),
            None,
        )
    patch = build_patch(record, body_text=body, final_url=final_url, fetched_at=stamp)
    return (EnrichmentResult(url, "enriched", before, after, final_url=final_url), patch)


def summarise(results: Iterable[EnrichmentResult]) -> dict[str, Any]:
    rows = list(results)
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.status] = counts.get(row.status, 0) + 1
    enriched = [row for row in rows if row.status == "enriched"]
    return {
        "schema_version": "ai26.rss_body_enrichment/1",
        "examined": len(rows),
        "counts": dict(sorted(counts.items())),
        "chars_before": sum(row.chars_before for row in rows),
        "chars_after": sum(row.chars_after for row in enriched),
        "enriched": [row.as_dict() for row in enriched],
        "failures": [row.as_dict() for row in rows if row.status == "failed"],
        "skipped": [row.as_dict() for row in rows if row.status == "skipped"],
    }


def select_records(
    records: Sequence[Mapping[str, Any]], *, limit: int | None = None, max_chars: int = SHORT_TEXT_CHARS
) -> list[Mapping[str, Any]]:
    """Shortest first: the worst offenders are repaired first, and the run is bounded either way."""
    candidates = [record for record in records if needs_enrichment(record, max_chars=max_chars)]
    candidates.sort(key=lambda record: (len(stored_text(record).strip()), source_url(record)))
    return candidates[:limit] if limit else candidates
