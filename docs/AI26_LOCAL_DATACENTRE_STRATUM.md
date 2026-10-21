# AI26 local data-centre stratum — evidence and open decisions (#296)

**Status: resolved (#296).** The grassroots arena now samples a labelled municipal
data-centre **news-discovery** stratum (tracked row added in PR #299), and every record
it produces declares that its identity is an aggregator while the publisher travels
beside it as provenance. The national-advocacy layer is unchanged: the discovery
stratum is *additional* and explicitly not an actor sample.

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
`active = true`. The payload shape was measured, and the row now declares what
that shape means:

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

That is why the row declares its identity, and the collector stamps it:

```toml
source_identity = "aggregator"
aggregator = "google_news"
```

```python
source.raw_metadata["source_identity"] = "aggregator"
source.raw_metadata["aggregator"] = {"provider": "google_news",
                                   "publisher_url": "https://www.cbsnews.com",
                                   "publisher_name": "CBS News"}
```

`source_url` stays the item's stable identity (the aggregator token); the publisher
never has to be recovered later because it is captured at collection from the item's
`<source>` element. A row without the declaration is read as a publisher feed, so the
marker keeps its meaning.

## 4. The decisions, and how they were resolved

**D1 -- is an aggregator acceptable as a collection source?** Yes, *as a marked
discovery stream*, never as a publisher. The declaration above is what separates
"a headline that exists" from "a corpus that silently believes Google is a
publisher". What it still costs, stated plainly: these records are
headline-plus-timestamp, so they evidence *that* coverage exists, not what a
campaign or a council actually said. Analysis must read
`source_identity == "aggregator"` as discovery, not as an actor document.

**D2 -- which stratum does the grassroots arena carry?** The news-discovery stratum
(the row merged in PR #299, now marked). The alternatives stay documented:

| option | status |
|---|---|
| 1. Municipal documents | available and mechanically pinned (`web_source` row -> page fetched and upserted, test-guarded). The higher-fidelity expansion: one ordinance, one text. Needs a town list, which is a sampling rule for the owner. |
| 2. State / utility-commission layer | **ruled out on evidence** (see §2): nine institutional endpoints returned 403/404/no connection. |
| 3. News-discovery layer | **sampled**, marked as aggregator, headline-only. |
| 4. Out of scope | superseded by (3); the honest fallback paragraph for §4.1 if the stratum is ever dropped. |

Option 1 is additive when it comes: `source_identity` keeps the two strata
separable, so adding municipal documents does not re-mean the discovery stream.

## 5. What the evidence supports

The discovery stratum answers "did the wave happen, and where" today, at headline
fidelity. If the paper needs what a council *decided*, option 1 is the next
increment, bounded to towns that adopted or formally debated a moratorium
(Gilchrist County FL, Hayward CA, the Danville / statewide-Virginia campaign): one
`web_source` row per institutional page, with the inclusion criterion written into
that row's `sampling_rationale`. Option 2 stays closed unless a scraper stage
exists.

## 6. The manifest shape a municipal layer would take (not present yet)

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
