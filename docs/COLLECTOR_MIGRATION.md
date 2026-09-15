# Collector migration map

This repository is the canonical implementation home for reusable LaclauGPT data collection. The migration deliberately preserves behavior, not historical directory layouts.

## Sources audited

- `TomiToivio/LaclauGPT-Discourse-Analysis/collector/`
- `TomiToivio/LaclauGPT-TikTok-Scraper`

The legacy TikTok repository contains a Firefox extension plus a Node backend. The current discourse-analysis collector added multi-platform browser capture, typed normalization concepts, scheduling and media/provenance handling. Operational study configuration, account lists, browser profiles and research data are deliberately excluded from this public repository.

## Migration matrix

| Source capability | New home | Status | Notes |
|---|---|---|---|
| Canonical records/provenance | `src/laclaugpt_data_collection/models.py` | ALREADY_IMPLEMENTED | Pydantic public interchange model retained as the canonical contract. |
| Platform parser common helpers | `collectors/platforms/` | ALREADY_IMPLEMENTED | Platform parsing remains isolated from storage. |
| TikTok parser | `collectors/platforms/tiktok.py` | ALREADY_IMPLEMENTED | Reused/refactored before this issue. |
| Instagram parser | `collectors/platforms/instagram.py` | ALREADY_IMPLEMENTED | Reused/refactored before this issue. |
| X/Twitter parser | `collectors/platforms/twitter.py` | ALREADY_IMPLEMENTED | Reused/refactored before this issue. |
| Bluesky collection | `collectors/bluesky.py` | ALREADY_IMPLEMENTED | Standalone collector retained. |
| RSS collection | `collectors/rss.py` | ALREADY_IMPLEMENTED | Feed collection stays optional. |
| Local SQLite/filesystem storage | `storage/local.py` | ALREADY_IMPLEMENTED | Preferred local-first backend. |
| MongoDB/Redis/S3 adapters | `storage/remote.py` | ALREADY_IMPLEMENTED | Optional distributed integrations. |
| Browser capture envelope | `capture.py` | REIMPLEMENT_CLEANLY | Typed, deterministic and platform-neutral. |
| Local capture endpoint | `capture_server.py` | REIMPLEMENT_CLEANLY | Standard-library HTTP service, localhost by default. |
| Firefox extension | `browser/firefox/` | REIMPLEMENT_CLEANLY | Explicit user-triggered capture, minimal permissions. |
| Legacy Firefox automatic scraping | archaeological reference | OBSOLETE | Silent/continuous interception is not the public default. Platform parsers remain available for sanitized captured payloads. |
| Legacy Node backend | current Python package | OBSOLETE | Replaced by typed Python capture/storage stack. |
| Media references | `models.py` | ALREADY_IMPLEMENTED | Canonical records carry references, not embedded blobs. |
| Media transfer implementation | storage/adapter boundary | REIMPLEMENT_CLEANLY | Network transfer is optional and must be supplied by an explicit adapter/deployment. Metadata capture never requires download. |
| Scheduler | external scheduler/CLI invocation | REIMPLEMENT_CLEANLY | Scheduling should invoke the same package entry points rather than duplicate pipeline logic. |
| Study/account YAML with real targets | private operations config | PRIVATE_OR_OPERATIONAL_DO_NOT_COPY | Public repository contains examples/placeholders only. |
| Browser profiles/cookies/session state | external ignored storage | PRIVATE_OR_OPERATIONAL_DO_NOT_COPY | Never committed. |
| Raw captures/research corpora/media | external data storage | PRIVATE_OR_OPERATIONAL_DO_NOT_COPY | Never committed. |
| Analysis/codebooks/LLM logic | other LaclauGPT modules | OBSOLETE HERE | Explicitly out of scope for Data Collection. |

## Browser design

The canonical Firefox extension lives under `browser/firefox/`. It does not embed credentials, study targets or private endpoints. By default it sends a user-triggered capture to `http://127.0.0.1:8765/capture`. The extension extracts only the current page URL, a conservative text summary, Open Graph media references, document title and a detected platform label.

This is intentionally safer than the historical scraper. Continuous API interception can capture far more session data than a researcher intended, so it is not enabled by default. More specialized capture adapters may be developed separately, but they must keep the same typed capture/canonical-record boundary and document their permissions.

## Data flow

```text
Firefox / platform collector / feed adapter
        |
        v
BrowserCapture or collector-specific raw payload
        |
        v
validation + platform normalization
        |
        v
NormalizedRecord
        |
        +--> SQLite / JSONL / CSV / filesystem (local)
        |
        +--> MongoDB / Redis / S3-compatible object storage (optional)
```

`source_url` and stable platform identifiers are preserved for downstream Analysis. Provenance records capture method and transformation history. Media remain references unless an explicit deployment chooses to download them.

## Privacy boundary

Only synthetic fixtures and placeholder configuration may be committed. Never add real target lists, collected records, HTML/network captures, cookies, browser profiles, media, transcripts, SQLite research databases, MongoDB dumps, credentials, CSC project paths or private endpoints.

## Historical note

Useful ideas retained from the old TikTok scraper include Firefox-assisted acquisition, capturing stable source identifiers and keeping browser extraction separate from backend persistence. The Node backend and broad automatic capture layout are retired in favor of the installable Python package and explicit capture contract.
