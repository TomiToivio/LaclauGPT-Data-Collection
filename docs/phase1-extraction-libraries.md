# Collection/extraction library inventory

Status: **Candidate backlog scaffold. Not wired into the current runtime.**

## Existing baseline

The repository already exposes BeautifulSoup, Scrapy, trafilatura and minet through the
`web-mining` optional extra, with Playwright separately available for browser automation. These
remain the preferred baseline and are not replaced here.

## Optional Python adapters

The `phase1-extraction` extra contains readability-lxml, extruct, dateparser, warcio and
selectolax. Imports are lazy. The new `extraction/` package is not imported by the current runtime
modules. Readability is a fallback, extruct is metadata-only, dateparser normalizes messy source
dates, warcio supports archival interchange, and selectolax is reserved for later benchmarking.

## Browser candidates

`browser/phase1/` is intentionally not referenced by the Firefox manifest. It declares Mozilla
Readability, Turndown and LinkeDOM for later bundled/offline evaluation. No code is loaded remotely
at runtime.

## R utilities

`scripts/R/` contains isolated researcher-side validation/import examples. R remains outside the
normal collector execution path.

## Activation gate

Before adopting these adapters, benchmark candidate extractors against the existing trafilatura/minet
path on representative synthetic/public fixtures. Record extractor name/version in derived-field
provenance, preserve canonical source URL/timestamp/raw fidelity, and reject any adapter that changes
current defaults or introduces discourse-analysis interpretation.
