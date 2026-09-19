# Phase 1 browser extraction adapters

This directory is deliberately disconnected from `browser/firefox/manifest.json` and the
Phase 0 capture path.

Candidates:
- `@mozilla/readability`: live-DOM main-content extraction.
- `turndown`: deterministic researcher-readable HTML to Markdown conversion.
- `linkedom`: Node-side DOM parsing for tests and offline tools.

No remote runtime code is allowed. Bundle dependencies before any future extension activation.
`compromise` is intentionally not included until a concrete metadata-only use case is demonstrated.
