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

## Live deployment and verification (2026-11-26, Laskin)

The deployed manifest held four #474 feed rows while the tracked plan held two:
`us_house_homeland` (US House Committee on Homeland Security) and `uk_dsit_ai`
(UK Department for Science, Innovation and Technology) had been deployed with
their rationale but never declared in Git, so every cycle reported
`source manifest DRIFT: deployed 109 vs tracked 107 (feed: 54->52)` and the
collection window silently left both rows out. Declaring them in
`configs/studies/ai26.sources.example.toml` — same rows, same rationale, no new
sampling decision — is what makes the audit and the runtime agree:

```
$ python scripts/check_ai26_runtime_sync.py
AI26_RUNTIME_SYNC=in_sync sources=sync study=sync code=sync
```

The arena's `sampling_focus` now names all three articulations the declared
sources actually provide: a congressional bill stream, a congressional committee
stream, and a non-EU ministry stream (with the UK read as supplemental, not a
fourth core region). One full declared pass (`--max-feeds 60 --limit 300`)
produced, per feed, records that are all `arena=parliamentary`,
`handoff.status=ready`, dated and text-bearing:

| feed | records | ready | dated | text |
| --- | --- | --- | --- | --- |
| `us_congressional_bills` | 5 | 5 | 5 | 5 |
| `us_house_homeland` | 5 | 5 | 5 | 5 |
| `uk_ai_security_institute` | 1 | 1 | 1 | 1 |
| `uk_dsit_ai` | 0 | — | — | — |

The parliamentary arena rose from 1 689 to 1 708 records (corpus 12 623). The
DSIT row's zero is expected rather than a fault: its newest entry is
2026-08-24, before the 2026-09-10 publication floor, and the row's own rationale
warns that it is a low-frequency stream.

Two limits stay visible. The GovInfo feed publishes general bills, so five new
records are legislative text whose AI relevance is resolved downstream, not at
collection; the committee feed is a press-release stream with the same property.
Neither source guarantees that a specific AI bill enters the arena, and no
analysis of the new records has run yet: the seed order still reaches priority-3
X before any P2 feed only when the earlier tiers are exhausted, so coverage in
`ai26__analysis_results` lags collection by construction.
