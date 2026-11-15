# The `elites × fi` cell: measurement, options, and what the rules already say (#424)

This is the decision record the issue asks for. It contains no sampling change: adding sources is an
owner decision, and this document exists so that decision can be made against live numbers rather than
a paragraph.

## Measurement (Laskin, 2026-11-15, ready frame 2026-09-01..2026-12-31)

```
ready in window        5,047
elites                 2,620
fi (all arenas)          336
elites × fi               30     <- source: etla, 30 of 30
```

So the Finnish elite layer is **1.1 % of the elite arena and 8.9 % of all Finnish material, drawn from
one institutional voice**. The rest of the Finnish strata are genuinely multi-actor (grassroots 177:
sttk, finland_datacentre_ai_news, teollisuusliitto, sak, sitra, jhl; parliamentary 125: sdp,
vasemmistoliitto, valtioneuvosto, vihreat, kokoomus). The thinness is specific to the elite cell.

## What the rules already say

The Phase 1 protocol — as amended for #88 — already covers this case without a new decision:

> A subgroup of 30 or more still requires adequate category prevalence and non-degenerate marginals;
> 30 is a reporting guardrail, not a power or reliability guarantee. Any pooling … must be preregistered,
> theoretically justified and accompanied by named components and denominators.

and §4.2 now requires that sparse cells "remain exploratory or qualitative checks without separate
agreement estimates".

**A 30-record cell from a single source fails the spirit of that guardrail before it fails the letter:**
the 30 are one institution's editorial line, so "inter-coder agreement on Finnish elite articulations"
would be measuring agreement about one outlet's output. Under the existing rule the cell is therefore
reported **descriptively** (n=30, single source) with no separate agreement estimate, and it is not
pooled into `elites` — pooling would hide that the Finnish elite articulation is measured through ETLA
alone.

That reading changes no data and no label; it is the conservative interpretation of a rule that is
already in force. If the owner prefers option 1, this record is superseded rather than edited.

## Option 1 — add Finnish elite sources (verified candidates, not applied)

Verified live on 2026-11-15 from Laskin. Institutional position and visibility only; no ideological
label is attached to any of them.

| candidate | route | live check | note |
| --- | --- | --- | --- |
| Sitra | RSS `https://www.sitra.fi/feed/` | HTTP 200 | already present in the grassroots arena; would need an arena decision, not a new row |
| Sitra | Bluesky `sitra.fi` | profile resolves | same entity as above — do **not** double-count across arenas |
| Aalto University | Bluesky `aalto.fi` | profile resolves | research institution; check posting volume before adding |
| University of Helsinki | Bluesky `helsinki.fi` | profile resolves | ditto |
| VTT | RSS `https://www.vtt.fi/rss` | HTTP **403** | not reachable unauthenticated; would need another route |
| ETLA | Bluesky | profile **not found** | current single source is RSS-only |

Before adding any of these to the elite arena, three things must hold, and none of them is free:

1. **Arena assignment is a claim about institutional position**, not about content: a research
   institute's feed is elite-arena material because of who speaks, not because of what they say.
2. **Volume must be checked**, because a feed that posts monthly changes a 30-record cell into a
   34-record cell — the cell size is the problem, and one more quiet source does not fix it.
3. **Tracked plan and deployed manifest must move together**, or the drift check reports `in_sync:
   false` and the collector silently keeps the old set.

Even if all four reachable candidates were added and each produced the same volume as ETLA, the cell
would reach roughly 120 records across five voices — enough to stop being single-source, still not
enough to be a *stratum*. Option 1 is therefore a real improvement in validity and a marginal
improvement in size; it should not be sold as making the cell large.

## Recommendation

Report `elites × fi` descriptively now (option 2, under the existing rule), and treat option 1 as a
**separate** sampling change with its own justification and its own measured effect on the cell — not
as a silent side effect of wanting a bigger number. The one thing that must not continue is the current
silence: a 30-record single-source cell described in the same table as multi-actor cells.

## What this document does not do

It does not add a source, edit the deployed manifest, or change `paper/PHASE_1_PAPER.md`. §4.2 already
carries the rule that makes the descriptive reading correct; the paper needs no edit for option 2, and
option 1 is an owner decision with a cost this record quantifies.
