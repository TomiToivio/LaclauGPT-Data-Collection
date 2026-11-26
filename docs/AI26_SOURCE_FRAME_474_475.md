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
