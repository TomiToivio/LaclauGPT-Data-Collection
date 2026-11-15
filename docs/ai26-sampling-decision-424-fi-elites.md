# AI26 Phase 1 sampling decision: Finnish elite cell (#424)

Date: 2026-11-15. Status: provisional reporting decision; re-audit before final freeze.

## Observed frame

Two readings an hour apart, on the live frame (window 2026-09-01 through 2026-12-31, Collection main @ `2357cc0`):

| reading | ready | elites | elites × fi | source |
| --- | --- | --- | --- | --- |
| 16:00 EET | 5,039 | 2,615 | 30 | etla (30 of 30) |
| 17:00 EET | 5,047 | 2,620 | 30 | etla (30 of 30) |

`fi` across all arenas: **336**. So the Finnish elite layer is **1.1 %** of the elite arena and **8.9 %** of all Finnish material, drawn from one institutional voice. The rest of the Finnish strata are genuinely multi-actor (grassroots 177: sttk, finland_datacentre_ai_news, teollisuusliitto, sak, sitra, jhl; parliamentary 125: sdp, vasemmistoliitto, valtioneuvosto, vihreat, kokoomus). The thinness is specific to the elite cell.

These are historical measurements, not a live recount.

## Decision

Report `elites × fi` **descriptively and exploratorily only**, with source concentration disclosed. Do not report independent subgroup agreement or generalize the cell to Finnish elites. Do not pool it into a broader elite estimate merely to satisfy a numerical threshold. Retain the records in the frame where otherwise eligible; no ideological source reclassification.

This follows the Phase 1 paper's §4.2 small-cell condition: independently double-coded cases are needed for reported subgroup agreement; small cells may be pooled only with a stated theoretical justification, otherwise they remain exploratory/qualitative. The n≥10 aggregate cell threshold does **not** by itself establish independent source or actor coverage.

A 30-record cell from a single source fails that condition's spirit before its letter: agreement would be measured against one institution's editorial line, so "agreement on Finnish elite articulations" would describe ETLA's output, not the elite stratum. The decision therefore changes no data and needs no new rule — it is the conservative application of a rule already in force.

## Suggested Phase 1 reporting sentence

"The Finnish-language elite cell (n=30 in the 2026-11-15 audit) is derived entirely from one institutional source, ETLA. We therefore treat it as an exploratory descriptive cell and do not estimate separate subgroup agreement or interpret it as representing Finnish elite discourse generally."

## The alternative, and what it would cost

Adding sources is the only way to make the cell a stratum, and it is a separate sampling change rather than a side effect of wanting a larger number. Candidates verified live on Laskin, 2026-11-15 (institutional position and visibility only; no ideological label):

| candidate | route | live check | note |
| --- | --- | --- | --- |
| Sitra | RSS `https://www.sitra.fi/feed/` | HTTP 200 | already in the **grassroots** arena; moving it would double-count an entity across arenas |
| Sitra | Bluesky `sitra.fi` | profile resolves | same entity as above |
| Aalto University | Bluesky `aalto.fi` | profile resolves | check posting volume before adding |
| University of Helsinki | Bluesky `helsinki.fi` | profile resolves | ditto |
| VTT | RSS `https://www.vtt.fi/rss` | HTTP **403** | not reachable unauthenticated |
| ETLA (current sole source) | Bluesky | profile **not found** | RSS-only |

Three costs are real: arena assignment is a claim about institutional position rather than content; volume has to be measured (one quiet feed turns 30 records into 34); and the tracked plan and the deployed manifest must move together or the drift check silently keeps the old set. Even all four reachable candidates at ETLA's volume yields roughly four voices and ~120 records — enough to stop being single-source, still not a stratum.

## Revisit conditions

If new, independently justified Finnish elite sources become available, verify actual access and collection permissions, document the institutional/visibility rationale, and update the tracked study plan and deployed source manifest together. Do not reopen the X stratum (#396) as an ad hoc sampling repair. Audit language provenance and duplicated items before reclassifying the cell. Re-measure the frame and independent double-coding coverage before claiming separate agreement.

## Verification still required

- Recompute the final frozen frame by arena × language × source and identify the denominator/window.
- Confirm independent double-coded cases for every subgroup agreement estimate.
- Apply the final wording in `paper/PHASE_1_PAPER.md` in the main LaclauGPT repository, which is the governing Phase 1 paper; this Collection decision record does not modify the locked paper automatically.

Language provenance for this cell improved on 2026-11-15: 70 blank labels were resolved by the backfill described in `docs/AI26_RSS_BODY_ENRICHMENT.md`, and enrichment now labels records as it fetches them (#423). The cell's size did not change, because the missing evidence was never text — it was actors.
