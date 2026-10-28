# AI26 operational gates for issues #368 and #369

## X capture (#368)
The hourly non-browser stage deliberately defers X. Green hourly reports therefore
**do not prove X collection works**. On Laskin, schedule an authorized browser
capture with a single auditable run ID per run, *then* run the freshness check as
a separately monitored scheduled step. Example (timestamp file produced by the
actual capture exporter or a read-only Mongo aggregation):

```bash
python scripts/check_ai26_capture_freshness.py \
  --captures-json /approved/private/ai26/latest_captures.json \
  --max-age-hours 24
```

Input format: `{"x":"2026-10-28T10:00:00Z"}`. The timestamp MUST be the
latest actual captured_at, not the collector's schedule timestamp or article
publication time. Exit status 2 means stale/missing/future provenance. The
command neither captures X nor installs cron; a live scheduler and capture
source must be configured and verified by the Laskin operator. Until then,
treat X as a convenience sample, not representative continuous sampling.

## Future publications (#369)
The AI26 realtime eligibility gate excludes source publication dates more
than 24 hours ahead of current UTC time, preserving the original timestamp
and using `future_source_publication_time` as the exclusion reason. The grace
period accommodates date-only and timezone ambiguity; event date must not be
substituted for publication date. Existing ready Mongo records are NOT
backfilled by this code change. Audit/rebuild those existing handoffs
separately with dry-run/provenance and verify the published-at distribution
before declaring the issue closed.

## Sampling and language (#360, #361)
Neither a legislative source nor a new observation period is authorized by
this patch. Issue #360 requires a study-owner sampling decision and an
actually verified Eduskunta API parser. Issue #361 has forward-looking RSS
full-content detection and a provenance-preserving language backfill already
on main; retain insufficient-text and low-confidence missing labels and
confirm actual post-change corpus counts before closure.
