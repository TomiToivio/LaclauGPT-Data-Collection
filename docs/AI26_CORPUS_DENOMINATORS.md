# AI26 corpus denominator and provenance (issues #321 and #322)

The durable `ai26__records` collection is a preservation store, **not** the
analysis denominator. Collection may retain excluded records for diagnostic
purposes. Published corpus sizes, platform shares and source concentration must
use the analysis-grade subset: `handoff.status != "excluded"`, with the study's
publication floor and sampling scope documented alongside the figure.

Report both totals separately when auditing: durable store records and
analysis-grade records. Never interpret growth in the store total alone as new
discourse. In particular, historical URL-only X shells from 2026-10-22 were
backed up and removed (see issue #322); downstream metrics should not depend on
such cleanup for correctness.

A configured `web_source` landing page is discovery input, **not** evidence of
a publication date. Analysis-ready web documents require an actual article/feed
publication time. Source discovery remains bounded and must follow the site's
declared study topic and arena; link relevance is not established by a date.

For implementation and regression tests, see the already merged fixes in PRs
#324 (web discovery), #323 (hollow capture rejection) and #326 (mirror refusal
reporting). PR #325's overlapping implementations are superseded by those
changes; the conflict resolution retains the tested `main` versions.
