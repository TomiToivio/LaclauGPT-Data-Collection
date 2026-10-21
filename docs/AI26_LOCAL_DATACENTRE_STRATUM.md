# AI26 local data-centre stratum — evidence and open decisions (#296)

**Status: two decisions pending with the study owner. A news-discovery row is now
in the manifest (added by PR #299) and its source-identity question is unresolved.**

The grassroots arena names "data centres, energy and environmental conflict" in its
`sampling_focus`, and its datacentre group is a *national advocacy* layer
(`foxglovelegal.bsky.social`, `nodesertdatacenter.com`, EFF / Creative Commons /
Food & Water Watch). Municipal campaigns — the level at which moratoriums are
adopted — are invisible to it.

## 1. The gap, re-measured 2026-10-21 (read-only, `ai26__records`)

Store total 1835 records, grassroots arena 333. Full-text search over
`content.text`, `content.title` and `raw_capture.payload.title`, case-insensitive:

| term | records |
|---|---|
| `Danville` | **0** |
| `Gilchrist` | **0** |
| `Hayward` | **0** |
| `walkout` | **0** |
| `Pittsylvania` | **0** |
| `Berry Hill` | **0** |
| `ordinance` | **0** |
| `moratorium` | 6 |
| `data center` | 53 |
| `data centre` | 15 |

The 19–20 October wave (Danville / statewide-Virginia pause campaign, the Gilchrist
County one-year moratorium, the Hayward 45-day emergency moratorium, the `#FreezeAI`
campus walkouts) is absent from a store that does hold 68 "data center/centre"
records — a stratum gap, not a vocabulary gap.

## 2. What the Laskin stage can actually collect (probed 2026-10-21)

`LACLAUGPT_BROWSER=none`: only RSS/Atom, page fetch, Bluesky, Mastodon, arXiv and
YouTube run there. Each candidate was fetched with `curl -sSL --max-time 20`;
"items" is the entry count in the returned document.

| candidate | HTTP | content | verdict |
|---|---|---|---|
| Google News query feed, `"data center" moratorium` | 200 | 102 items | collectable — see §3 |
| Google News query feed, `"data center" Danville Virginia` | 200 | 73 items | collectable — see §3 |
| Virginia SCC news (`/news/rss.aspx`, `/rss`, `/news/`) | **403** | CloudFront block | not collectable |
| Virginia LIS (`lis.virginia.gov/rss/`) | 200 | 0 items, no feed | not collectable |
| California Energy Commission (`/rss/news`, `/rss`) | **404** | — | not collectable |
| CPUC (`/rss/news`, `/rss`) | **404** | — | not collectable |
| Florida PSC (`/rss/news`, `/`) | no response | — | not collectable |
| Virginia / Florida governor newsroom feeds | **404** | — | not collectable |
| Pittsylvania County VA, Halifax County VA (`/feed/`) | **404** | WordPress present, no feed | not collectable |
| City of Danville VA (`/feed/`) | no connection | — | not collectable |
| Virginia Mercury, Florida Phoenix | **403** | bot-blocked | not collectable |
| Gilchrist County BOCC (`gilchrist.fl.us/feed/`) | 200 | 1 item (meeting notice) | per-town feed, no ordinances |
| City of Hayward (`hayward-ca.gov/rss.xml`) | 200 | 10 items (city news) | per-town feed, no ordinances |
| California governor (`gov.ca.gov/feed/`) | 200 | 10 items | general politics, not municipal |
| Inside Climate News (`/feed/`) | 200 | 10 items | general news, not municipal |

Two conclusions follow directly:

1. **A state legislative / utility-commission layer does not exist as a collectable
   stream** at any path probed — nine institutional candidates returned 403, 404 or no
   connection. It would need HTML scraping of docket and bill-search pages, which the
   browser-free server stage does not do.
2. **Municipal documents are mechanically available, but not as a feed.** The
   repository already collects a page as a record: a manifest `web_source` row is
   fetched by `ai26_laskin_runner._records_for_job` and upserted by `source_url`, so a
   town's agenda or ordinance page is captured once and updated when it changes. That
   is a *document* stream at the rate the page changes, not a news stream.

## 3. The row that is now in the manifest, and what it actually carries

PR #299 added a Google News query feed (`local_data_centre_moratorium_news`) with
`active = true`. No code anywhere resolves or marks aggregator records, and the
payload shape was measured:

```
TITLE: Zohran Mamdani Backs Major Expansion of New York's Data Center Moratorium - Gizmodo
LINK : https://news.google.com/rss/articles/CBMipgFBVV95cUxOQk5naWpHaGRob1FiR1JKekI1LXo1...
DATE : Tue, 20 Oct 2026 13:10:14 GMT
SOURCE: ('https://gizmodo.com', 'Gizmodo')
```

So, for every record this feed will produce:

- **`source_url` is `news.google.com/<opaque token>`**, not the publisher's article.
  The publisher's *domain* is available only in the `<source url=…>` element, and the
  article URL is not in the feed at all (recovering it needs a redirect follow per
  item).
- **The payload is a headline, a timestamp and a publisher name.** There is no
  article text. A record from this stratum is therefore evidence *that coverage
  exists*, not a text of the campaign or the decision.
- It samples **coverage of** the campaigns, not the campaigns. A rally reported by
  four outlets is one event with four texts; a council resolution is one document
  with one text.

This is why the row is not simply "a source added": it changes what a record in the
grassroots arena *is*, and it needs the owner's decision on both points below.

## 4. The decisions still open

**D1 — Is an aggregator acceptable as a collection source?**
If yes, records from such a feed need an explicit identity marker (e.g.
`source.raw_metadata.source_identity = "aggregator"` plus the publisher domain kept
from `<source url>`), so that analysis never reads `news.google.com` as the publisher
and the corpus audit does not count one aggregator as a dominant source. That is a
code change plus a documented deviation from "the publisher URL is the record's
identity". If no, the row is removed and the stratum falls to option 1 or 4.

**D2 — Which stratum does the grassroots arena carry, and by what inclusion rule?**

| option | requires | yields | cost to the corpus |
|---|---|---|---|
| 1. Municipal documents | a defined **town list** (owner's sampling rule) | ordinances, resolutions — deterministic, verifiable | small, high precision, slow to arrive |
| 2. State / utility-commission layer | — | **not collectable** (§2): 403/404/no connection on every probed endpoint | would need a scraper stage |
| 3. News-query layer (the merged row) | a query set, no town list | 102 / 73 items measured; the exact wave is reachable | high volume, cross-outlet duplicates, headline-only records, aggregator identity (§3) |
| 4. Declare out of scope | one paragraph in §4.1's limitation text | nothing, but the paper stays honest | none |

Inclusion, when it happens, must be recorded as a sampling decision with its
criteria — institutional position, never an ideological classification of any actor.

## 5. A position (recommendation, not the decision)

Recommend **option 1, bounded to the towns that actually adopted or formally debated
a moratorium in the window** (Gilchrist County FL, Hayward CA, the Danville /
statewide-Virginia campaign's institutional page) as `web_source` rows, with the
inclusion criterion written into each row's `sampling_rationale`. Keep option 3 only
as a **separately labelled discovery stream** with the D1 marker, never as a
like-for-like actor sample. Do not pursue option 2. Option 4 is the honest fallback
if the paper does not need the local layer.

## 6. The manifest shape option 1 would take (NOT applied)

```toml
[[web_source]]
name = "gilchrist_county_bocc"
url = "https://gilchrist.fl.us/"
arena = "grassroots"
source_family = "local data-centre conflict / municipal decision"
sampling_rationale = "<which body, which decision, when, and the inclusion criterion>"
priority = "P2"
```

The row count, the town list and the inclusion wording are the owner's; the loader
needs nothing else.
