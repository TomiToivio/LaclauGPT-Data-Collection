# AI26 source decision: SAG-AFTRA AI (#219)

Decision (2026-10-22): **retire** `sag_aftra_ai` from the tracked hourly sampling plan, without silently substituting another actor.

## Evidence and scope

- As documented in issue #219, the configured SAG-AFTRA contracts/AI URL returned 403 consistently from the Laskin collector and produced zero stored records; 65 blocked occurrences were reported by 2026-10-22.
- The SAG-AFTRA general RSS URL was reported stale (most recent item dated 2024-08-15), below the 2026-09-01 publication floor. It is not an equivalent AI-contract feed.
- The actor is **not excluded from the research universe**. This removes only a nonfunctional automatic collection source, not existing data, a classification, or the research strand.
- This creates an explicit *coverage gap*: SAG-AFTRA primary-source evidence on creative-labour/AI contracts is not represented through this collector. Do not misinterpret absence of records as absence of activity.
- The Authors Guild is a potential **distinct actor**, not a direct SAG-AFTRA replacement. Its AI/copyright advocacy is relevant (including 2026 materials), but its collection endpoint, extraction, and sampling comparability need their own verification before inclusion.

## Deployment

The tracked plan is `configs/studies/ai26.sources.example.toml`. The live Laskin file `data/config/ai26.sources.toml` may be ignored/untracked and **is not changed by this commit**. On Laskin, remove the exact `[[web_source]]` stanza named `sag_aftra_ai` from the deployed configuration and run the existing config-drift validation. Confirm one hourly cycle no longer reports `web_source:sag_aftra_ai: web_fetch_failed` and that unrelated source collection still succeeds.

Preserve the issue's prior source-health diagnostics; source failures must continue to report partial status rather than quietly becoming successful cycles.

Sources: https://github.com/TomiToivio/LaclauGPT-Data-Collection/issues/219 and https://authorsguild.org/news/
