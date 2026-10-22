# AI26 `web_source` feed discovery — decision and evidence (#321)

**Status: option (a), implemented as feed discovery only.** A `web_source` no longer
depends on a two-entry hardcoded map to reach the analysis corpus: the browser-free
stage reads the feed the page itself advertises and collects *that* through the
existing RSS collector, so its articles arrive with a publication time.

Option (b) — stage-scoping `collection_policy.fetch_external_links_as_web_sources` so
the config stops declaring a capability this node lacks — was **not** taken. The
policy keys in `configs/studies/ai26.example.yaml` are unchanged, and no
`web_source` row was added or removed.

## 1. The defect, in one paragraph

`ai26_laskin_runner.py` handled a `web_source` in one of two ways: if the row's
homepage was a key of `_WEB_SOURCE_FEED_FALLBACKS`, its feed was collected and the
articles arrived dated; every other row produced one page-level snapshot with no
publication time, which the handoff then excluded as
`missing_source_publication_time`. Two keys existed (`openai.com/news`,
`microsoft.com/en-us/ai/blog`), so every other `web_source` was confined to the
undated branch — 1 of 1962 analysis-grade records on 2026-10-22.

## 2. What the code does now

Precedence inside the `web_source` branch, in order, and it stops at the first that
applies:

| # | Route | Result |
|---|---|---|
| 1 | homepage is a key of `_WEB_SOURCE_FEED_FALLBACKS` | the mapped feed is collected and **the homepage is not fetched at all**. An explicit override always wins. |
| 2 | the served page declares `<link rel="alternate" type="application/rss+xml">` or `application/atom+xml` | the declared feed is collected; articles are dated. Relative `href`s are resolved against the post-redirect page URL. |
| 3 | no map entry and no declaration | today's behaviour, unchanged: one undated snapshot record |
| 4 | page fetch fails (403, timeout, …) | today's behaviour, unchanged: `SourceJobError("web_fetch_failed", status_code=…)`, which the cycle reports as a blocked source |
| 5 | a declared feed is collected but carries no items | one snapshot (never two) plus a warning naming the source and the feed |

### Bounds

* **One homepage request per `web_source` per cycle, not two.** Discovery reads the
  body of the single `fetch_web_child` call the snapshot path already made; the
  decoded HTML rides on `WebFetchOutcome.html`. That means the discovery step adds
  no request, no timeout budget and no latency to the cycle — the fetch keeps the
  client, redirect loop guard, host validator, `max_bytes` and 20 s timeout it had.
* **One feed per source per cycle** (`limit=1` in `discover_feed_urls`), collected
  through `RSSCollector`.
* **The per-source share is the feed's depth.** `_web_source_feed_records` passes
  `max_items_per_feed=per_source_limit` and also truncates the returned list, so a
  feed publishing 100 items cannot eat a neighbouring source's allocation. A zero or
  negative share is clamped to 1 rather than collecting nothing.
* **The `type` filter is load-bearing.** `eu_ai_policy` and `finland_government`
  carry `rel="alternate"` links for *language* versions of the page; without the
  RSS/Atom MIME-type check those would be collected as if they were feeds.

## 3. Verification against the twelve configured homepages (laskin01, 2026-10-22)

Real network, the shipping code (`fetch_web_child` → `discover_feed_urls` →
`RSSCollector`, `per_source_limit=5`), one page fetch per source:

| `web_source` | page | feed | feed URL | dated / sampled |
|---|---|---|---|---|
| `anthropic_news` | 200 | no | — | snapshot |
| `dario_amodei_essays` | 200 | no | — | snapshot |
| `google_deepmind_blog` | 200 | no | — | snapshot (page is JS-rendered; its feed is already a separate `[[feed]]` row) |
| `meta_ai` | 200 | no | — | snapshot |
| `microsoft_ai_blog` | override | yes | `https://www.microsoft.com/en-us/ai/blog/feed/` | 5/5 (feed carries 10) |
| `dair_blog` | 200 | no | — | snapshot |
| `pause_ai` | 200 | **yes** | `https://pauseai.info/rss.xml` | 5/5 (feed carries 121, 26 dated; newest 2026-07-06, i.e. below the 2026-09-01 floor today) |
| `eu_ai_policy` | 200 | no | — | snapshot |
| `finland_government` | 200 | no | — | snapshot |
| `fcai` | 200 | yes (empty) | `https://fcai.fi/home?format=rss` | 0/0 → snapshot + warning |
| `food_water_watch_data_centers` | 200 | **yes** | `https://www.foodandwaterwatch.org/feed/` | 5/5 (feed carries 10, newest 2026-10-22) |
| `humans_first_data_centers` | 200 | no | — | snapshot |

Net effect today: one source family (`food_water_watch_data_centers`, a grassroots
data-centre source) newly contributes dated, in-window articles; `pause_ai` becomes
dated but its newest item predates the publication floor, so it will contribute from
the first post after 2026-09-01; `fcai` advertises an empty feed and keeps its
snapshot. `anthropic.com` and `ai.meta.com` declare no feed at all — the code says so
by taking route 3, with no crash and no second snapshot — which confirms the issue's
earlier probe (404 on their guessed feed paths).

## 4. Not implemented: article-link extraction, and why

For pages that publish dates but expose no feed, the remaining fix is to extract
article links from the homepage, fetch each child, and carry its publication time.
It was measured read-only on 2026-10-22 and deliberately **not** implemented:

* **Link selection is a heuristic, not a declaration.** `anthropic.com/news` offers
  135 same-origin links whose first entries are category pages
  (`/news/announcements`), not articles. A URL-pattern heuristic would store a
  listing page as an article.
* **Two of the four probed sites state no machine-readable publication time on their
  article pages at all.** `ai.meta.com` articles carry neither `article:published_time`
  nor JSON-LD `datePublished`; `dair-institute.org` blog posts carry neither either.
  Dating them would mean guessing a format from rendered text.
* **Where a date does exist it can be the page's, not the article's.** A listing page
  that does carry `article:published_time` would be stored with the newest post's date
  under the listing's own URL — a wrong publication time attached to a wrong identity.

The corpus's publication floor is computed from `source.created_at`, so a wrong date
is worse than a missing one: it would silently admit material into analysis-grade
form. That is a sampling judgement for the owner, not an agent default.

## 5. What would legitimately close the rest

In rough order of provability:

1. A `[[feed]]` row for any source whose operator publishes a feed path that the
   homepage does not declare (as was done for DeepMind and Google AI in `2508c09`).
   This is a config decision, verified by hand, not a heuristic.
2. Accepting a feed URL that the page links as an ordinary `<a href>` (still the
   publisher's own statement, no date parsing). On 2026-10-22 none of the eight
   remaining homepages linked an RSS/Atom URL this way, so this would add nothing
   today.
3. Article-link extraction, if ever, with a per-site inclusion rule that the owner
   sets and a fixture per site — and only where the article page states its own
   publication time.

## 6. Tests

`tests/test_issue_321_web_source_feed_discovery.py` (25 tests): discovery from an RSS
link, the Atom variant, relative `href` resolution, the `type` filter, the one-feed
cap, override-wins (asserting the homepage is never fetched), the snapshot fallback
compared field-by-field against the pre-#321 path, non-HTML pages, an empty
discovered feed producing one snapshot and one warning, 403 and timeout preserving
today's `SourceJobError`, the per-source cap (including a zero share), and that the
manifest still has its twelve `web_source` rows.
