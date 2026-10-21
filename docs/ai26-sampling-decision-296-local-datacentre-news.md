# AI26 sampling decision — the local data-centre news layer (#296)

**Status: decided 2026-10-21.** The study owner authorised this sampling decision
("do these and close them"); it is recorded here with its inclusion criteria and
the measurement that produced it. Sampling provenance is not an ideology label:
no actor is classified ideologically, and `source_family` explains *why material
is sampled*, never what an actor "is".

The checked-in example manifest (`configs/studies/ai26.sources.example.toml`) is
**not** the deployed private `data/config/ai26.sources.toml`. Reconciling the
deployed file is a separate deployment step for the owner. Nothing here deletes
or relabels records already in the store.

Index of this round's decisions: `docs/ai26-sampling-decisions-2026-10-21.md`.

---

## The decision: option 3, a bounded news-query layer

**Decision.** Option 3 of the issue: a **news-query layer**, two rows, in the
grassroots arena. Not a per-town list (option 1, which needs a pre-declared
jurisdiction set), not the state/utility-commission layer (option 2 — nine
institutional endpoints probed 403/404/no connection on the browser-free stage),
and not "out of scope" (option 4), because the wave is reachable today.

```toml
[[feed]]
name = "local_data_centre_moratorium_news"
feed_url = "https://news.google.com/rss/search?q=%22data+center+moratorium%22&hl=en-US&gl=US&ceid=US:en"
arena = "grassroots"
source_identity = "aggregator"
aggregator = "google_news"
priority = "P2"

[[feed]]
name = "local_data_centre_pause_news"
feed_url = "https://news.google.com/rss/search?q=%22data+center+pause%22&hl=en-US&gl=US&ceid=US:en"
arena = "grassroots"
source_identity = "aggregator"
aggregator = "google_news"
priority = "P2"
```

**Inclusion criteria.** By *topic*: the phrases "data center moratorium" and
"data center pause", US English edition, no geography filter beyond that and no
named town, campaign or outlet. Verified live 2026-10-21: 102 and 100 items, the
first containing the Danville/statewide-Virginia moratorium campaign reporting and
the Gilchrist County and Hayward votes. **No actor is classified ideologically**;
the rows carry no claim about any town's, campaign's or outlet's politics.

**What a record in this stratum is, stated plainly.** It samples **coverage of the
campaigns, not the campaigns themselves**. A council resolution is one document
with one text; a rally reported by four outlets is one event with four texts. Every
record is a headline, a timestamp and a publisher — there is no article text, and
`source_url` is a `news.google.com` token rather than the publisher's article (the
publisher domain arrives in the feed's `<source url=…>` element). Analysis must
attribute by that element and must never read `news.google.com` as the publisher.

**How it is bounded.** Exactly two query rows (not ten, not a per-town list). At
`per_source_limit = 5` the pair contributes at most 10 records per cycle, and
#293's rotation polls it once per full manifest pass (~9 h at 36 enabled feeds).
`P2` so news coverage never displaces a first-party `P1` source in the bounded
window.

**Aggregator identity.** Both rows declare `source_identity = "aggregator"` and
`aggregator = "google_news"` (the mechanism merged in #309). Collection therefore
stamps `source.raw_metadata.source_identity = "aggregator"` plus an `aggregator`
block carrying the publisher url and name taken from the item's `<source>` element,
while `source_url` stays the item's stable identity. Analysis reads that marker as
*discovery*, never as an actor document, and never reads `news.google.com` as the
publisher. `docs/AI26_LOCAL_DATACENTRE_STRATUM.md` records the same contract.

**What this does not do.** It does not collect municipal ordinances, resolutions,
agendas or public comments (option 1) — that remains a separate decision requiring
a pre-declared jurisdiction list and a document-level inclusion rule. Nor does the
marker turn a headline into a council decision: the payload is
headline-plus-timestamp, so a record evidences *that* coverage exists, not what a
campaign or a council said.

---

## Verification (owner's deployment step)

1. Deploy the two rows and confirm both appear in a cycle's
   `tick_budget.rss_feed_window.window` within one full pass.
2. Confirm new records carry `arena = "grassroots"`,
   `source_name = local_data_centre_{moratorium,pause}_news`, and a
   `source_url` under `news.google.com` with a headline-only payload.
3. Re-run the #296 term counts (`Danville`, `Gilchrist`, `Hayward`, `walkout`,
   `moratorium`) against the store and record the delta as evidence — the
   stratum's purpose is that these are no longer zero.
