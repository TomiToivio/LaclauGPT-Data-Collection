# RSS body enrichment (#416)

A third of the ready RSS stratum stored a headline and nothing else. `tech_policy_press` was 196 of
196 records at a mean of 62 characters, `openai_news` 118 of 118 at 197, `datacenterdynamics` 141 of
142 at 146 — and `tech_policy_press` alone is 22.7 % of the parliamentary arena, the arena that is
simultaneously the smallest and the least language-labelled.

## Why the collector was not at fault

The feeds publish titles and no bodies:

```
curl -sL https://www.techpolicy.press/rss/feed.xml   # 0 <description>, 0 <content:encoded>
curl -sL https://openai.com/news/rss.xml             # descriptions 168–184 chars, no <content:encoded>
curl -sL https://www.datacenterdynamics.com/en/rss/  # descriptions 72–133 chars, no <content:encoded>
```

`collectors/rss.py` already prefers the longest of `excerpt` and `full_text`, and the same stratum
proves the path works: `lesswrong_frontpage` stores ~16,000 characters per record and 486 ready RSS
records exceed 2,000. The difference is that those publishers syndicate the article.

## What the enrichment does

For a ready RSS record whose stored text is under `--max-chars` (default 300), fetch the article URL
with the collector's own guarded fetcher — host validation, redirect limit, content-type allowlist,
5 MB cap — and store the extracted visible text:

| Field | Change |
| --- | --- |
| `content.text` | replaced with the article body |
| `human_readable.summary` | regenerated from the new text |
| `provenance` | one entry appended: `transformations: ["rss-body-enrichment"]`, `module: external-link-fetcher`, `visited_url` = the article URL, `metadata.reason` |
| `source_url`, `handoff`, `source`, `raw_capture` | **unchanged** — the record keeps its identity |

Extraction prefers `readability-lxml` when installed and falls back to the stdlib visible-text parser,
which already skips `<script>/<style>/<noscript>`. The fetcher's own `_html_text` regex is deliberately
*not* used: it keeps `<style>` blocks, which would put CSS in the first 400 characters of the analysis
unit.

## Guardrails

- **A thin page is skipped, not stored.** A fetch must yield at least `MIN_GAIN_CHARS` (300) characters
  *and* `MIN_GAIN_FACTOR` (2×) more than the stored text. A paywall stub, a cookie banner or a
  redirect to a homepage is recorded as `skipped` with the reason, never applied.
- **Idempotent.** The provenance marker is the state: an enriched record is no longer a candidate, so a
  second run costs nothing and cannot duplicate provenance.
- **Bounded and worst-first.** `--limit` caps a run; selection is ordered by stored-text length, so the
  most unusable records are repaired first and a run can be stopped at any point.
- **Dry run by default.** `--apply` is required to write.

## Running it

```bash
cd /mnt/workspace/LaclauGPT-Data-Collection
set -a && . ./.env >/dev/null 2>&1 && set +a

.venv/bin/python scripts/enrich_rss_bodies.py --limit 20                      # dry run
.venv/bin/python scripts/enrich_rss_bodies.py --apply --limit 20              # write 20
.venv/bin/python scripts/enrich_rss_bodies.py --apply --limit 100 --source tech_policy_press
```

Measured on Laskin, first applied batch (`tech_policy_press`, 20 records):

```
counts: {enriched: 20}
chars_before: 756          chars_after: 488,397
```

That is 37 characters per record before and ~24,400 after — the articles exist; the feed simply never
carried them. 887 ready RSS records were still under 300 characters after that batch, so the queue is
`--limit`-many runs away, not one.

## What it does not do

It does not re-fetch records that already have text, rewrite any identity field, or change collection
behaviour.

## The language label the body makes possible (#423)

Enriching the text did not relabel anything retroactively, and that turned out to matter: `resolve_language`
had already run while the record held a 62-character title, so it returned `insufficient_text` and the
blank stayed. Fifty-two `tech_policy_press` records moved from "title, no language" to "full article
body, still no language" — the evidence to label them sat in the document, unused.

Two changes close that:

* **Live enrichment labels the body it stores.** When a record's `source.language` is blank, the same
  patch that writes `content.text` now resolves the language from that body, writing
  `source.language`, `source.raw_metadata.language_method` and a blank `language_backfill` (the previous
  value, for reversibility — the same contract `scripts/backfill_ai26_language.py` writes). A label that
  already exists is never replaced, and a failed detection leaves the label blank, records the refusal
  reason in the enrichment provenance (`language_from_body`), and still applies the body.
* **The existing population is repaired by the backfill tool**, which was already written for exactly
  this: `scripts/backfill_ai26_language.py` fills blanks from the stored text, dry-run by default, and
  never guesses (short text, missing detector and low confidence all stay blank).

```bash
.venv/bin/python scripts/backfill_ai26_language.py              # dry run: how many are labelable now
.venv/bin/python scripts/backfill_ai26_language.py --apply      # write labels + method + previous value
```

The cycle's own summary now carries `languages_resolved` and `language_methods`, so an enrichment run
that gains text but cannot label says so instead of looking complete.
