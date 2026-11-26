# AI26 source-frame correction (#474, #475)

The locked paper is unchanged. The tracked YAML and TOML now correct MIRI's X
identity, add its official Bluesky presence, and add two bounded P2 RSS/Atom
sources: US congressional bills (both chambers, GovInfo) and the UK AI Security
Institute (supplemental non-EU governance, not a fourth core comparison region).
The former is a general legislative feed; downstream relevance assessment is
necessary and it cannot guarantee coverage of all AI bills. Public source
identities are sampling provenance, not ideology. No media collection or X
stratum reopening is authorized.

## Runtime deployment and historical correction

On Laskin and the localhost bridge, reconcile the tracked plan with the actual
runtime files following docs/AI26_SOURCE_DEPLOYMENT.md. Review the dry run and
back up both files; the obsolete X identity is a deliberate removal, but do not
use a broad removal override if other private sources would disappear. Update
the actual bridge target inventory separately; use the #470 drift audit. Keep
the prior raw records and provenance intact. Do not rename the unrelated
account to MIRI. Exclude records belonging to the misidentified X account from
the analytical sample, recording an explicit provenance-based sampling
exclusion and revised denominators; do not delete source records. The study
owner must review the exact exclusion set and analysis-side mechanism before
any store mutation. Match the X platform and exact case-insensitive author
identity, not text or language. Recheck URL-level analysis matches before
applying an exclusion. Include arena-blank records in this audit.

After deployment verify actual feed parsing, dated text-only output, canonical
source URLs, and arena provenance; do not treat a successful config parse as
coverage. Recheck corpus-audit and the bridge target report. No live host or
MongoDB access was available for this patch, so existing records are unchanged
and new source coverage is not yet verified.

## Aggregate-only acceptance audit

After loading the trusted private runtime environment on Laskin:

```bash
python scripts/audit_ai26_source_frame_474_475.py
```

The audit reads the AI26 collections but never writes to them. It counts actual
records, dated text and ready handoffs for the two new parliamentary feeds;
counts confirmed historical wrong-account records (including blank-arena X
captures and URL-proven identities), ambiguous identities requiring human review,
and exact URL matches with analysis results; and counts the corrected MIRI X
and Bluesky identities separately. It prints aggregate counts only. This is not
a disposition decision, publication-date bypass, or guarantee of broad regional
coverage. The operator should repeat it after a collection cycle and record the
sanitized results on #474 and #475 before closure.

### Historical wrong-account quarantine

A confirmed old X status URL with corroborating or absent author/platform is
excluded from new AI26 handoffs with reason `ai26_wrong_miri_account`. A conflicting
identity is not automatically changed. To assess existing records:

```bash
python scripts/reconcile_ai26_wrong_miri_handoffs.py
```

Review the counts and the audit. Pause the analysis consumer before an approved
repair to avoid racing an in-flight analysis job. Only then run the command with
`--apply`. It changes the handoff status and reason of confirmed records without
existing exact-URL analysis results, preserving identity, raw data, revision and
provenance. Resume the analysis consumer after re-running the audit and reviewing
any conflicts or pre-existing analysis results separately. The audit additionally
reports `usable_dated_text`: records meeting all four parliamentary acceptance
conditions simultaneously, rather than unrelated aggregate counts.
