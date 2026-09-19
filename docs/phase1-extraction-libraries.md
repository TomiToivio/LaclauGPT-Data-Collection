# Phase 1 collection/extraction library inventory

Status: **Phase 1 backlog scaffold. Not active in Phase 0.**

## Existing baseline

The repository already exposes BeautifulSoup, Scrapy, trafilatura and minet through the
`web-mining` optional extra, with Playwright separately available for browser automation. These
remain the preferred baseline and are not replaced here.

## Optional Python adapters

The `phase1-extraction` extra contains readability-lxml, extruct, dateparser, warcio and
selectolax. Imports are lazy. The new `extraction/` package is not imported by Phase 0 runtime
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

Before Phase 1 activation, benchmark candidate extractors against the existing trafilatura/minet
path on representative synthetic/public fixtures. Record extractor name/version in derived-field
provenance, preserve canonical source URL/timestamp/raw fidelity, and reject any adapter that changes
Phase 0 defaults or introduces discourse-analysis interpretation.
