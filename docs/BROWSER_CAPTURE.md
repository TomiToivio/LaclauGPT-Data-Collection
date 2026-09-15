# Browser capture extension

`src/laclaugpt_data_collection/browser/firefox/` contains a minimal Firefox Manifest V3 extension for a **user-triggered local workflow**. It is disabled by default. Clicking the toolbar action toggles capture, and the extension sends only public request metadata to `http://127.0.0.1:8765/captures`; it contains no credential, cookie, target list, or remote endpoint.

The extension does not download media and does not silently capture response bodies. A local capture service may validate a `BrowserCapture` payload and pass it to `ingest_browser_capture`, which normalizes supported synthetic/public platform data through the existing collector parsers. Operators must provide informed research governance and configure any browser debugging/body capture outside this public extension.

## Migration map

| Historical source | Disposition |
| --- | --- |
| `collector/backend/records.py`, `normalize_captures.py` | Reimplemented by `models.py`, `normalize.py`, and `collectors/ingest.py`. |
| `collector/modules/*`, `bluesky.py` | Already represented by isolated platform parsers and Bluesky collector. |
| `collector/store.py` | Reimplemented by backend-neutral storage with SQLite local default. |
| `collector/backend/scheduler.py`, media download workers | Retained as future optional adapters; no scheduler or media download runs implicitly. |
| `collector/browser/*`, `collector/firefox/*` | Reimplemented as opt-in local browser boundary and minimal Firefox extension. |
| legacy TikTok scraper's study fields, `localhost:3000` endpoints, storage context | Deliberately excluded as project-specific/operational. |
