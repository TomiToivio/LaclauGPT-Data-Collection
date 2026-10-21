# AI26 sampling decisions prompted by issues #293–#296 (2026-10-21)

These are **candidate sampling changes**, not ideological labels. Phase 1 theory and methodology remain unchanged. The checked-in example manifest is not the deployed private `data/config/ai26.sources.toml`; reconcile the latter explicitly before deployment.

## #293: RSS allocation

Use bounded, fair RSS polling: preserve the 40-record tick cap and its 20-record RSS reservation under default settings. Process at most four feeds of five items per tick; rotate four feeds per tick. With 32 configured feeds, the ideal revisit cadence is eight hourly ticks, not hourly. Do not describe this as hourly per-feed polling. More frequent sampling needs an explicit higher throughput budget.

## #295: scholarly governance query

The example manifest proposes title-field governance terms instead of all-field matching for generic `evaluation` or `audit`. This is deliberately **not** an update of the deployed private manifest. Evaluate retrieval and false-positive rate across the arXiv backend before activating it. Previously stored off-topic records are not deleted or retroactively relabelled; the contaminated historical stratum needs a documented exclusion or re-audit when constructing analytical samples.

The ETUI numeric-month date parser is a code fix. Existing rows with missing dates require a separate, audited re-ingestion or repair from their original publisher timestamps.

## #294: parliamentary language and source strata

Audit `source.language` and provenance `language_method` for parliamentary documents; confirm that optional `langdetect` is installed on Laskin. Do not infer Finnish merely because a source is Finnish, and never fill `unknown` with English. Backfill only from measured content or publisher-declared language, leaving ambiguous cases unknown. The present governmental/RSS/scholarly sources do not constitute a parliament-debate or party-programme sample. Before adding first-party sources, define jurisdiction (FI/EU/US), actor/party coverage, date window, document types, deduplication and legal/API access, then update the tracked plan and deployment manifest together.

## #296: grassroots local data-centre campaigns

Recommended initial design for review: event-based municipal documents (ordinances, hearing agendas, public comments and resolutions) at a **predeclared** set of jurisdictions chosen by a transparent rule, not by their presumed positions. Candidate sites from the issue (Danville, Gilchrist County, Hayward) are a test set only, not a representative sample. Distinguish first-party campaign speech from local-government decisions and news reports *about* campaigns. Capture publisher timestamps and provenance. Prefer a defined event window and publish inclusion/exclusion rules before inserting new sources. National advocacy feeds are not interchangeable with local campaigns.

## Deployment acceptance

1. Test the allocated RSS feeds and rotation, including the empty/small-budget cases; confirm `records_collected <= rss_allocation` on typical feeds and that no fetched feed is silently discarded due solely to the known budget mismatch.
2. Regression-test ETUI timestamp parsing; re-ingest original raw records to fill missing published_at rather than fabricate dates.
3. Compare old/new scholarly query yield and topical precision before approval; document the corpus discontinuity.
4. Measure parliamentary language nonblank rate by source, with `unknown` preserved. Verify selected new strata independently once the sampling rule is signed off.
5. Validate on Laskin before closing the corresponding issues. The code/documentation merge does not imply deployment verification.
