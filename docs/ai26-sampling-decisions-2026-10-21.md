# AI26 sampling decisions prompted by issues #293–#296 (2026-10-21)

**Status: superseded by the three decision records below.** The owner authorised
the decisions on 2026-10-21; each now lives in its own file, with the measurement
that produced it and the inclusion criteria it will be deployed under:

* `docs/ai26-sampling-decision-293-feed-cadence.md` — bounded and fair RSS rotation
* `docs/ai26-sampling-decision-295-governance-query.md` — the `ai_governance` query
* `docs/ai26-sampling-decision-296-local-datacentre-news.md` — the local data-centre
  news layer

The deployment acceptance list from the earlier draft is kept in the #293 record,
which owns the cycle-level checks; #295 and #296 each carry their own verification
step.

## #294 — parliamentary language and source strata (unchanged by this round)

Audit `source.language` and provenance `language_method` for parliamentary
documents; confirm that optional `langdetect` is installed on Laskin. Do not infer
Finnish merely because a source is Finnish, and never fill `unknown` with English.
Backfill only from measured content or publisher-declared language, leaving
ambiguous cases unknown. The present governmental/RSS/scholarly sources do not
constitute a parliament-debate or party-programme sample. Before adding first-party
sources, define jurisdiction (FI/EU/US), actor/party coverage, date window, document
types, deduplication and legal/API access, then update the tracked plan and
deployment manifest together (#294, #307).

Each decision above carries its own verification list in its own file; the
cycle-level checks (window position, stored-set size, no HTTP 400, grassroots
arena) belong to the record that changed them, so a deployment is verified against
the decision it implements.
