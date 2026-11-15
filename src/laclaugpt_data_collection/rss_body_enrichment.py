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
* **A gained body is a gained language label (#423).** `source.language` was resolved while the record
  still held a 62-character title, so a record that gained a body kept a blank label and its evidence
  to resolve one. When the stored label is blank, the enrichment now detects the language of the body
  it just stored and writes it in the same patch, with the method and the previous value. A label that
  already exists is never replaced, and a detection that fails leaves the label blank and records why.
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
    #: Language resolved from the stored body, when the record arrived without one (#423).
    language: str = ""
    language_method: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "status": self.status,
            "chars_before": self.chars_before,
            "chars_after": self.chars_after,
            "detail": self.detail,
            "final_url": self.final_url,
            "language": self.language,
            "language_method": self.language_method,
        }


def resolved_language_for_body(record: Mapping[str, Any], body_text: str) -> tuple[str, str]:
    """Detect the language of the body the enrichment just stored (#423).

    #416 gave headline-only records an article body but left ``source.language`` blank, because the
    label was resolved when the record still held a 62-character title: 52 records moved from
    "title, no language" to "full article body, still no language", and the arena-by-language cells
    stayed computed over indeterminate cases even though the evidence to resolve them was now stored.

    Two constraints, both from #294:

    * a label that already exists is never replaced — a platform value (Bluesky ``langs``, a feed's
      ``xml:lang``, arXiv metadata) or a declared row language wins over a detection;
    * unknown stays unknown. ``resolve_language`` returns an empty tag when the text is short, the
      detector is missing, or no candidate reaches its confidence floor, and the patch is then
      applied without a language rather than with a guess.
    """
    source = record.get("source")
    if isinstance(source, Mapping) and str(source.get("language") or "").strip():
        return "", ""
    from .language import resolve_language

    return resolve_language(body_text)


def enrichment_provenance(
    *,
    final_url: str,
    visited_url: str,
    fetched_at: str,
    chars: int,
    language: str = "",
    language_method: str = "",
) -> dict[str, Any]:
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
            # #423: the outcome of resolving a label from this body — a method when a label was
            # written, the refusal reason ("detector_unavailable", "low_confidence", …) when it was
            # not, and "" when nothing was attempted because the record arrived labelled.
            "language_from_body": language_method,
        },
    }


def build_patch(
    record: Mapping[str, Any],
    *,
    body_text: str,
    final_url: str,
    fetched_at: str,
    language: str = "",
    language_method: str = "",
) -> dict[str, Any]:
    """The MongoDB update document for one enriched record. Pure, so the tests can inspect it."""
    url = source_url(record)
    text = body_text.strip()
    provenance = list(record.get("provenance") or [])
    provenance.append(
        enrichment_provenance(
            final_url=final_url,
            visited_url=url,
            fetched_at=fetched_at,
            chars=len(text),
            language=language,
            language_method=language_method,
        )
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
    if language:
        # #423: the body that made this record labelable is now stored, so the label is resolved
        # from it in the same write. Only a blank is filled — a declared or platform-observed tag is
        # never replaced — and the previous value is kept for reversibility, exactly as
        # scripts/backfill_ai26_language.py writes it.
        patch["source.language"] = language
        patch["source.raw_metadata.language_method"] = language_method
        patch["source.raw_metadata.language_backfill"] = ""
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
    # #423: the body is now the labelable text, so resolve the language from it in the same pass.
    language, language_method = resolved_language_for_body(record, body)
    patch = build_patch(
        record,
        body_text=body,
        final_url=final_url,
        fetched_at=stamp,
        language=language,
        language_method=language_method,
    )
    return (
        EnrichmentResult(
            url,
            "enriched",
            before,
            after,
            final_url=final_url,
            language=language,
            language_method=language_method,
        ),
        patch,
    )


def summarise(results: Iterable[EnrichmentResult]) -> dict[str, Any]:
    rows = list(results)
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.status] = counts.get(row.status, 0) + 1
    enriched = [row for row in rows if row.status == "enriched"]
    labelled = [row for row in enriched if row.language]
    return {
        "schema_version": "ai26.rss_body_enrichment/1",
        "examined": len(rows),
        "counts": dict(sorted(counts.items())),
        "chars_before": sum(row.chars_before for row in rows),
        "chars_after": sum(row.chars_after for row in enriched),
        # #423: an enriched record that gained a language label is the repair of the "new body, old
        # blank label" population; count it, so a cycle that enriches but still cannot label says so.
        "languages_resolved": len(labelled),
        "language_methods": dict(
            sorted(
                (method, sum(1 for row in labelled if row.language_method == method))
                for method in {row.language_method for row in labelled}
            )
        ),
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
