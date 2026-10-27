# AI26 Phase 1: legislative evidence and language-label release decisions

Tracked from [#359](https://github.com/TomiToivio/LaclauGPT-Data-Collection/issues/359), [#360](https://github.com/TomiToivio/LaclauGPT-Data-Collection/issues/360), and [#361](https://github.com/TomiToivio/LaclauGPT-Data-Collection/issues/361).

## Parliamentary arena (#360)

The 2026-10-26 Laskin audit found **614 analysis-grade records** assigned to the parliamentary arena, but **zero Eduskunta legislative sources**. These 614 records are mainly executive and institutional press communications. They cannot demonstrate legislative debate, written questions, committee proceedings, or the uptake of grassroots claims in lawmaking.

**Sampling decision proposed:** retain the parliamentary arena as a target, but do not describe its present observations as legislative evidence. Add an official Eduskunta record source, preferring dated parliamentary debate sections or written questions with a documented 2026 observation window, *only after verifying access, lawful reuse, reliable publication timestamps, and a bounded parser*. Do not relabel institutional press as speeches. Track document type and institution as source metadata so the legislative and executive strata can be measured separately. Until verified, language in the Phase 1 paper must say 'institutional and executive communications; legislative stratum not yet collected'.

**Acceptance:** an official public endpoint tested against dated 2026 items, parser fixtures, publication-floor enforcement, separate legislative document type, and an audit demonstrating nonzero legislative records. Zero is the accurate count until then.

## Pause AI release approval (#359)

The tracked `pause_ai` source is disabled following #347 because five fetched records per cycle all fell below the publication floor. This is a deliberate coverage removal, not a TOML formatting change.

The release owner must approve this **specific** removal, then run on Laskin after checking the active-identity diff:

```bash
python scripts/deploy_ai26_sources.py
python scripts/deploy_ai26_sources.py --apply --allow-removals
python scripts/check_ai26_runtime.py
```

Do not interpret a merged PR as deployment. The check now tolerates comment-only / ordering-only TOML differences but retains a failing result for an active toggle.

## Unlabelled analysis-grade material (#361)

On 2026-10-26: 3,578 analysis-grade records, 1,071 unlabelled (29.9%). The measured labelled subset is 2,507, not 3,578. Language shares should state both denominators and an explicit *unknown* bucket. In particular, 95 Finnish-labelled records does **not** mean only 95 Finnish-language items exist.

The RSS collector now checks publisher-supplied full feed article bodies when present; it does not infer from URLs or source nationality, overwrite source declarations, or relax the confidence threshold. This only affects future ingestion of suitable feed entries. Web-enriched content, arXiv, the other platforms, and historical MongoDB rows still need separate measurement and possibly repairs.

**Backfill gate:** before changing the 1,071 historical rows, preview candidates read-only with counts by platform and arena; preserve every original value and record detection method, confidence, model version and change timestamp; require an explicit approval and a bounded, resumable write phase. Rows with insufficient text, missing detector, or confidence below 0.90 stay unlabelled. Re-run the exact analysis-grade denominator query after backfill and compare cross-tabs.
